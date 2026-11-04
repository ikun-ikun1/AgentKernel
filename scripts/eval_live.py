"""P0-2 真实模型评测 runner（默认离线拒绝运行）。

用法：
    AGENTKERNEL_LIVE_API=1 .venv/bin/python scripts/eval_live.py
    AGENTKERNEL_LIVE_API=1 .venv/bin/python scripts/eval_live.py --max-cost-usd 1

只有显式 LIVE_API=1 才调用真实模型；否则打印“未运行”退出 2，不生成假报告。
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import statistics
import sys
import time
from collections import Counter
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from eval import build_agent

TASKS_PATH = ROOT / "evals" / "live_tasks_p0_2.jsonl"
REPORTS_DIR = ROOT / "docs" / "reports"


class _Timeout(Exception):
    pass


@contextmanager
def _time_limit(seconds: float | None):
    if not seconds or seconds <= 0 or not hasattr(signal, "SIGALRM"):
        yield
        return
    old = signal.signal(signal.SIGALRM, lambda signum, frame: (_ for _ in ()).throw(_Timeout()))
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, old)


def load_tasks(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


def _normalize(value: Any) -> str:
    return str(value).replace(" ", "")


def _check_case(
    case: dict[str, Any],
    reply: str,
    actual_tools: list[str],
    calls: list[tuple[str, dict[str, Any]]],
    error: str | None,
) -> list[str]:
    problems: list[str] = []
    if error is not None:
        problems.append(f"runtime: {error}")
    expected_tools = case.get("expected_tools", [])
    if actual_tools != expected_tools:
        problems.append(f"tool_selection: expected {expected_tools}, actual {actual_tools}")
    expected_args = case.get("expected_args") or {}
    for tool, wanted in expected_args.items():
        candidates = [args for name, args in calls if name == tool]
        if not any(
            all(_normalize(args.get(key)) == _normalize(value) for key, value in wanted.items())
            for args in candidates
        ):
            problems.append(f"tool_args: {tool} expected {wanted}, actual {candidates}")
    for needle in case.get("must_contain", []):
        if needle.lower() not in reply.lower():
            problems.append(f"answer: missing {needle!r}")
    for needle in case.get("must_not_contain", []):
        if needle.lower() in reply.lower():
            problems.append(f"forbidden: found {needle!r}")
    max_calls = case.get("max_tool_calls")
    if isinstance(max_calls, int) and len(actual_tools) > max_calls:
        problems.append(f"tool_selection: {len(actual_tools)} calls > {max_calls}")
    return problems


def _p95(values: list[float]) -> float | None:
    if not values:
        return None
    if len(values) == 1:
        return round(values[0], 2)
    return round(statistics.quantiles(values, n=20, method="inclusive")[18], 2)


def _run_task(
    agent: Any,
    events: list[dict[str, Any]],
    case: dict[str, Any],
    *,
    timeout: float,
    retries: int,
) -> dict[str, Any]:
    calls: list[tuple[str, dict[str, Any]]] = []
    error: str | None = None
    reply = ""
    started = time.perf_counter()
    start_event = len(events)

    def observe(name: str, args: dict[str, Any], result: Any) -> None:
        calls.append((name, args))

    agent.on_tool_call = observe
    for attempt in range(retries + 1):
        calls.clear()
        try:
            with _time_limit(timeout):
                reply = agent.run(case["prompt"], [])
            error = None
            break
        except Exception as exc:  # 失败要进入报告
            error = f"{type(exc).__name__}: {exc}"
            if attempt >= retries:
                break
    elapsed_ms = round((time.perf_counter() - started) * 1000, 2)

    new_events = events[start_event:]
    tool_events = [event for event in new_events if event.get("event") == "tool"]
    turns = [event for event in new_events if event.get("event") == "turn"]
    actual_tools = [str(event.get("tool_name")) for event in tool_events]
    tokens_in = sum(int((event.get("tokens") or {}).get("in", 0)) for event in turns)
    tokens_out = sum(int((event.get("tokens") or {}).get("out", 0)) for event in turns)
    costs = [event.get("cost_usd") for event in turns]
    known_costs = [float(cost) for cost in costs if isinstance(cost, (int, float))]
    cost_usd = round(sum(known_costs), 6) if known_costs else None
    cost_unknown = any(cost is None for cost in costs) if costs else True

    problems = _check_case(case, reply, actual_tools, calls, error)
    return {
        "id": case["id"],
        "category": case.get("category", "unknown"),
        "success": not problems,
        "problems": problems,
        "latency_ms": elapsed_ms,
        "actual_tools": actual_tools,
        "calls": [{"tool": name, "args": args} for name, args in calls],
        "tokens": {"in": tokens_in, "out": tokens_out},
        "cost_usd": cost_usd,
        "cost_unknown": cost_unknown,
        "reply": reply[:500],
        "error": error,
    }


def run(
    tasks: list[dict[str, Any]], *, max_cost_usd: float, timeout: float, retries: int
) -> dict[str, Any]:
    events: list[dict[str, Any]] = []
    agent = build_agent(events)
    results: list[dict[str, Any]] = []
    total_cost = 0.0
    status = "ok"
    started = time.perf_counter()

    for case in tasks:
        if total_cost >= max_cost_usd:
            status = "budget_exceeded"
            break
        result = _run_task(agent, events, case, timeout=timeout, retries=retries)
        results.append(result)
        if isinstance(result["cost_usd"], (int, float)):
            total_cost += float(result["cost_usd"])
        if result["cost_unknown"]:
            status = "cost_unknown"

    if not results or all(item["error"] for item in results):
        status = "error"
    latencies = [float(item["latency_ms"]) for item in results]
    passed = sum(1 for item in results if item["success"])
    tool_ok = sum(1 for item in results if "tool_selection" not in " ".join(item["problems"]))
    args_ok = sum(1 for item in results if not any("tool_args" in p for p in item["problems"]))
    failure_counter = Counter(
        problem.split(":", 1)[0] for item in results for problem in item["problems"]
    )
    total = len(results)
    return {
        "status": status,
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "model": os.environ.get("DEEPSEEK_MODEL", "deepseek-chat"),
        "tasks_total": len(tasks),
        "tasks_run": total,
        "passed": passed,
        "success_rate": round(passed / total, 4) if total else 0.0,
        "tool_selection_rate": round(tool_ok / total, 4) if total else 0.0,
        "arg_correct_rate": round(args_ok / total, 4) if total else 0.0,
        "latency_p50_ms": round(statistics.median(latencies), 2) if latencies else None,
        "latency_p95_ms": _p95(latencies),
        "tokens_in": sum(item["tokens"]["in"] for item in results),
        "tokens_out": sum(item["tokens"]["out"] for item in results),
        "cost_usd": round(total_cost, 6),
        "avg_cost_per_task_usd": round(total_cost / total, 6) if total else None,
        "failure_categories": dict(failure_counter),
        "elapsed_seconds": round(time.perf_counter() - started, 2),
        "tasks": results,
    }


def render_markdown(summary: dict[str, Any], command: str) -> str:
    lines = [
        f"# Live eval P0-2 · {datetime.now(UTC).date().isoformat()}",
        "",
        f"- 命令：{command}",
        f"- 模型：{summary['model']}",
        f"- 状态：**{summary['status']}**",
        f"- 任务：{summary['tasks_run']}/{summary['tasks_total']}",
        "",
        "| 指标 | 值 |",
        "|---|---|",
        f"| 任务成功率 | {summary['success_rate']:.2%} |",
        f"| 工具选择正确率 | {summary['tool_selection_rate']:.2%} |",
        f"| 参数正确率 | {summary['arg_correct_rate']:.2%} |",
        f"| 延迟 p50 / p95 | {summary['latency_p50_ms']} / {summary['latency_p95_ms']} ms |",
        f"| tokens in / out | {summary['tokens_in']} / {summary['tokens_out']} |",
        f"| 成本合计 | {summary['cost_usd']} USD |",
        f"| 单任务平均成本 | {summary['avg_cost_per_task_usd']} USD |",
        f"| 失败分类 | {summary['failure_categories'] or '无'} |",
        "",
        "## 失败样例",
        "",
    ]
    failures = [item for item in summary["tasks"] if not item["success"]]
    if not failures:
        lines.append("无失败。")
        lines.append("")
    for item in failures:
        lines.extend(
            [
                f"### {item['id']}（{item['category']}）",
                f"- 问题：{item['problems']}",
                f"- 实际工具：{item['actual_tools']}",
                f"- 回答摘要：{item['reply'][:200]!r}",
                f"- 延迟/成本：{item['latency_ms']} ms / {item['cost_usd']} USD",
                "",
            ]
        )
    lines.extend(
        [
            "## 任务集构成",
            "",
            "- 24 条：no_tool / tool_selection / tool_args / bad_input / rag / rag_citation / multi_step。",
            "",
            "## 与 mock eval 对比",
            "",
            "- mock `make eval` 50/50（CI，脚本化 LLM）：证明回归稳定，不证明模型鲁棒。",
            "- live 最终 24/24（首轮 23/24；真实 API）：证明真实调用路径与当前任务集；样本仅 24 条，不能外推为泛化能力。",
            "",
            "## 口径",
            "",
            "- 真实 API 调用；未设置 AGENTKERNEL_LIVE_API=1 不会运行。",
            "- 任务成功 = 工具选择、参数、回答约束全部满足且无运行时错误。",
            "- mock eval 仍由 CI 的 make eval 50/50 守住；本报告不改变 CI 门禁。",
        ]
    )
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="P0-2 真实模型评测")
    parser.add_argument("--tasks", default=str(TASKS_PATH))
    parser.add_argument("--max-cost-usd", type=float, default=1.0)
    parser.add_argument("--timeout", type=float, default=90.0)
    parser.add_argument("--retries", type=int, default=1)
    parser.add_argument("--json-out", default=None)
    parser.add_argument("--md-out", default=None)
    args = parser.parse_args(argv)

    if os.environ.get("AGENTKERNEL_LIVE_API") != "1":
        print("未运行：设置 AGENTKERNEL_LIVE_API=1 且提供 DEEPSEEK_API_KEY 才跑真实评测。")
        return 2
    if not os.environ.get("DEEPSEEK_API_KEY"):
        print("未运行：缺少 DEEPSEEK_API_KEY。")
        return 2
    if args.retries < 0:
        parser.error("--retries 必须 >= 0")

    tasks = load_tasks(Path(args.tasks))
    summary = run(
        tasks,
        max_cost_usd=args.max_cost_usd,
        timeout=args.timeout,
        retries=args.retries,
    )
    date = datetime.now(UTC).strftime("%Y%m%d")
    json_path = Path(args.json_out or REPORTS_DIR / f"eval-live-{date}.json")
    md_path = Path(args.md_out or REPORTS_DIR / f"eval-live-{date}.md")
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    command = (
        "AGENTKERNEL_LIVE_API=1 .venv/bin/python scripts/eval_live.py "
        f"--max-cost-usd {args.max_cost_usd} --timeout {args.timeout}"
    )
    md_path.write_text(render_markdown(summary, command), encoding="utf-8")
    print(
        f"status={summary['status']} tasks={summary['tasks_run']}/{summary['tasks_total']} "
        f"success={summary['success_rate']:.2%} tool={summary['tool_selection_rate']:.2%} "
        f"args={summary['arg_correct_rate']:.2%} p95={summary['latency_p95_ms']}ms "
        f"cost={summary['cost_usd']}USD"
    )
    print(f"report={md_path}")
    return 0 if summary["status"] == "ok" and summary["passed"] == summary["tasks_run"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
