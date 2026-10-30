"""轻量性能基线（维护期）：启动 / 单轮 ReAct / MCP / SQLite / MySQL。

用法：
    make bench
    python scripts/bench.py --runs 30 --json
    python scripts/bench.py --dsn mysql+pymysql://...   # 可选，写临时会话

只测本机延迟，不做容量规划；MySQL 未给 DSN 时自动跳过。
"""

from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from agentkernel.adapters.mcp.knowledge_server import KnowledgeMCPServer
from agentkernel.adapters.memory.sqlite_store import SQLiteStore
from agentkernel.memory.factory import create_runtime_store
from agentkernel.rag.knowledge import KnowledgeBase
from agentkernel.runtime.agent import Agent
from agentkernel.tools import builtin
from agentkernel.tools.registry import Registry


class _FastPathLLM:
    """只返回 final_answer：测的是 Agent 编排快路径，不是完整 ReAct。"""

    def chat(self, messages: list[dict[str, str]], **kwargs: Any) -> str:
        return '{"action": "final_answer", "action_input": "ok"}'

    def pop_usage(self) -> None:
        return None

    def last_model(self) -> str | None:
        return None


_TOOL_THEN_ANSWER = [
    '{"action": "calculator", "action_input": {"expression": "1+2"}}',
    '{"action": "final_answer", "action_input": "3"}',
]


class _ScriptedLLM:
    """按脚本先 tool_call 再 final_answer：覆盖工具执行与观察回灌。"""

    def __init__(self) -> None:
        self.responses: list[str] = []

    def reset(self) -> None:
        self.responses = list(_TOOL_THEN_ANSWER)

    def chat(self, messages: list[dict[str, str]], **kwargs: Any) -> str:
        if not self.responses:
            return '{"action": "final_answer", "action_input": "done"}'
        return self.responses.pop(0)

    def pop_usage(self) -> None:
        return None

    def last_model(self) -> str | None:
        return None


def _percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    index = min(len(ordered) - 1, math.ceil(fraction * len(ordered)) - 1)
    return ordered[index]


def _measure(fn: Callable[[], object], runs: int) -> dict[str, float]:
    samples: list[float] = []
    for _ in range(runs):
        started = time.perf_counter()
        fn()
        samples.append((time.perf_counter() - started) * 1000)
    return {
        "n": runs,
        "p50_ms": round(_percentile(samples, 0.50), 2),
        "p95_ms": round(_percentile(samples, 0.95), 2),
        "mean_ms": round(sum(samples) / len(samples), 2),
    }


def bench_cli(runs: int) -> dict[str, float]:
    def run() -> None:
        proc = subprocess.run(
            [sys.executable, "-m", "agentkernel", "--help"],
            cwd=ROOT,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        if proc.returncode != 0:
            raise RuntimeError(f"CLI --help 退出码 {proc.returncode}")

    return _measure(run, runs)


def bench_agent_fastpath(runs: int) -> dict[str, float]:
    """Agent 编排快路径（无工具、无压缩）；名字刻意不叫 ReAct 延迟。"""
    registry = Registry()
    builtin.register_builtin(registry)
    agent = Agent(registry, llm_client=_FastPathLLM())

    def run() -> None:
        agent.run("ping", [])

    return _measure(run, runs)


def bench_react_tool(runs: int) -> dict[str, float]:
    """一轮含 tool_call → 工具执行 → 观察回灌 → final_answer 的 ReAct 编排。"""
    registry = Registry()
    builtin.register_builtin(registry)
    client = _ScriptedLLM()
    agent = Agent(registry, llm_client=client)

    def run() -> None:
        client.reset()
        agent.run("1+2 等于几", [])

    return _measure(run, runs)


def bench_mcp(runs: int) -> dict[str, float]:
    kb = KnowledgeBase(persist_dir=None)
    try:
        kb.ingest_text("bench.md", "ReAct 是 Reasoning + Acting 的循环。")
        server = KnowledgeMCPServer(kb)

        def run() -> None:
            server.call_tool("knowledge_query", {"query": "ReAct", "top_k": 3})

        return _measure(run, runs)
    finally:
        kb.close()


def bench_sqlite(runs: int) -> dict[str, float]:
    store = SQLiteStore(":memory:")
    try:
        store.create_session("bench")
        counter = iter(range(runs))

        def run() -> None:
            store.append_message("bench", "user", f"message-{next(counter)}")

        return _measure(run, runs)
    finally:
        store.close()


def bench_mysql(dsn: str, runs: int) -> dict[str, float] | None:
    if not dsn:
        return None
    store = create_runtime_store(dsn)
    try:
        store.delete_session("bench-mysql")
        store.create_session("bench-mysql")
        counter = iter(range(runs))

        def run() -> None:
            store.append_message("bench-mysql", "user", f"message-{next(counter)}")

        return _measure(run, runs)
    finally:
        try:
            store.delete_session("bench-mysql")
        except Exception:
            pass
        store.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="AgentKernel 性能基线")
    parser.add_argument("--runs", type=int, default=20, help="每项采样次数（默认 20）")
    parser.add_argument("--dsn", default=None, help="可选 MySQL DSN；不传则跳过 MySQL 写入")
    parser.add_argument("--json", action="store_true", help="输出 JSON")
    args = parser.parse_args(argv)
    if args.runs < 1:
        parser.error("--runs 必须 >= 1")

    results: dict[str, dict[str, float] | None] = {
        "cli_startup": bench_cli(5),
        "agent_fastpath": bench_agent_fastpath(args.runs),
        "react_tool_turn": bench_react_tool(args.runs),
        "mcp_query": bench_mcp(args.runs),
        "sqlite_write": bench_sqlite(args.runs),
        "mysql_write": bench_mysql(args.dsn, args.runs) if args.dsn else None,
    }
    if args.json:
        print(json.dumps(results, ensure_ascii=False, indent=2))
        return 0

    print(f"{'metric':<16} {'p50(ms)':>10} {'p95(ms)':>10} {'mean(ms)':>10} {'n':>5}")
    for name, result in results.items():
        if result is None:
            print(f"{name:<16} {'skip':>10} {'skip':>10} {'skip':>10} {'0':>5}")
            continue
        print(
            f"{name:<16} {result['p50_ms']:>10.2f} {result['p95_ms']:>10.2f} "
            f"{result['mean_ms']:>10.2f} {int(result['n']):>5}"
        )
    print("注：本机单次采样，仅作维护期回归参考；MySQL 需显式 --dsn。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
