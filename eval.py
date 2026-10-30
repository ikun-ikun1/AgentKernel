"""数据驱动评估（G-32）：golden set 跑分。

用法：
    python eval.py                 # mock golden set（evals/golden_mock.jsonl，50 条，无需 API Key）
    python eval.py --live          # live golden set（evals/golden_live.jsonl，20 条，需 DEEPSEEK_API_KEY）

判定：mock 与 live 都要求 100% 通过，任一条失败即退出码 1。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from agentkernel.adapters.llm.openai_compatible import OpenAICompatibleClient
from agentkernel.adapters.mcp.client import InProcessMCPClient
from agentkernel.adapters.mcp.knowledge_server import KnowledgeMCPServer
from agentkernel.application.mcp_tools import register_mcp_tools
from agentkernel.ports.llm import LLMClient
from agentkernel.rag.knowledge import KnowledgeBase
from agentkernel.runtime.agent import Agent
from agentkernel.tools import builtin
from agentkernel.tools.registry import Registry

KB_TEXT = (
    "ReAct 是 Reasoning + Acting 的循环：思考 → 行动 → 观察 → 回复。"
    "AgentKernel 从零实现了 ReAct 主循环。"
)


class MockLLM:
    """按脚本吐模型输出，并记录每轮 messages（用于断言调用次数）。"""

    def __init__(self, responses: list[str]) -> None:
        self.responses = list(responses)
        self.calls: list[list[dict[str, str]]] = []

    def __call__(self, messages: list[dict[str, str]]) -> str:
        self.calls.append(messages)
        if not self.responses:
            return json.dumps({"action": "final_answer", "action_input": "（mock 脚本耗尽）"})
        return self.responses.pop(0)


class ScriptedLLMClient:
    """把脚本化 MockLLM 包装成 LLMClient，供 mock eval 注入。"""

    def __init__(self) -> None:
        self.handler: MockLLM | None = None

    def chat(self, messages: list[dict[str, str]], **kwargs: object) -> str:
        if self.handler is None:
            raise RuntimeError("ScriptedLLMClient 尚未设置 handler")
        return self.handler(messages)

    def pop_usage(self) -> None:
        return None

    def last_model(self) -> str | None:
        return "mock"


def build_agent(events: list[dict], llm_client: LLMClient | None = None) -> Agent:
    registry = Registry()
    builtin.register_builtin(registry)
    kb = KnowledgeBase()
    kb.ingest_text("notes.md", KB_TEXT)
    register_mcp_tools(registry, InProcessMCPClient(KnowledgeMCPServer(kb)))
    client = llm_client or OpenAICompatibleClient()
    return Agent(registry, llm_client=client, on_event=events.append)


def load_cases(path: Path) -> list[dict]:
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


def run_mock_case(case: dict) -> tuple[list[str], list[dict], list[dict], MockLLM]:
    events: list[dict] = []
    client = ScriptedLLMClient()
    agent = build_agent(events, client)
    history: list[dict[str, str]] = []
    turns = case.get("turns") or [{"prompt": case["prompt"], "responses": case["responses"]}]
    mock = MockLLM([response for turn in turns for response in turn["responses"]])
    client.handler = mock
    replies: list[str] = []
    for turn in turns:
        replies.append(agent.run(turn["prompt"], history))
    return replies, events, history, mock


def check_case(
    case: dict, replies: list[str], events: list[dict], history: list[dict], mock: MockLLM
) -> list[str]:
    expect = case["expect"]
    problems: list[str] = []
    last = replies[-1]
    tool_names = [event["tool_name"] for event in events if event["event"] == "tool"]

    if "reply_equals" in expect and last != expect["reply_equals"]:
        problems.append(f"回答应为 {expect['reply_equals']!r}，实际 {last!r}")
    for needle in expect.get("reply_contains", []):
        if needle not in last:
            problems.append(f"回答缺少 {needle!r}：{last!r}")
    if "tool_calls" in expect and tool_names != expect["tool_calls"]:
        problems.append(f"工具调用应为 {expect['tool_calls']}，实际 {tool_names}")
    if expect.get("must_cite") and "来源" not in last and "notes.md" not in last:
        problems.append(f"回答未带来源：{last!r}")
    if expect.get("fallback") and tool_names:
        problems.append(f"应按纯文本降级，实际调用了 {tool_names}")
    if "history_min" in expect and len(history) < expect["history_min"]:
        problems.append(f"历史条数应 ≥{expect['history_min']}，实际 {len(history)}")
    if "max_llm_calls" in expect and len(mock.calls) > expect["max_llm_calls"]:
        problems.append(f"模型调用应 ≤{expect['max_llm_calls']}，实际 {len(mock.calls)}")
    return problems


def run_mock(path: Path) -> int:
    cases = load_cases(path)
    failures = 0
    for case in cases:
        try:
            replies, events, history, mock = run_mock_case(case)
            problems = check_case(case, replies, events, history, mock)
        except Exception as exc:  # 单条失败不影响其余用例
            problems = [f"异常：{type(exc).__name__}: {exc}"]
        if problems:
            failures += 1
            print(f"[FAIL] {case['id']} ({case['category']})")
            for problem in problems:
                print(f"       - {problem}")
        else:
            print(f"[PASS] {case['id']} ({case['category']})")
    total = len(cases)
    print(f"\n通过 {total - failures}/{total}（mock）")
    return 0 if failures == 0 else 1


def run_live(path: Path) -> int:
    cases = load_cases(path)
    events: list[dict] = []
    agent = build_agent(events)
    failures = 0
    for case in cases:
        try:
            reply = agent.run(case["prompt"], [])
            ok = case["expect_contains"] in reply
        except Exception as exc:  # 记录后继续
            reply = f"ERROR {type(exc).__name__}: {exc}"
            ok = False
        if not ok:
            failures += 1
            print(f"[FAIL] {case['id']} 期望包含 {case['expect_contains']!r}：{reply[:120]}")
        else:
            print(f"[PASS] {case['id']}")
    total = len(cases)
    print(f"\n通过 {total - failures}/{total}（live）")
    return 0 if failures == 0 else 1


def main() -> None:
    parser = argparse.ArgumentParser(description="AgentKernel golden set 评估")
    parser.add_argument("--live", action="store_true", help="跑真实 API live golden set")
    parser.add_argument("--golden", default=None, help="mock 数据集路径")
    parser.add_argument("--live-golden", default=None, help="live 数据集路径")
    args = parser.parse_args()

    if args.live:
        sys.exit(run_live(Path(args.live_golden or ROOT / "evals" / "golden_live.jsonl")))
    sys.exit(run_mock(Path(args.golden or ROOT / "evals" / "golden_mock.jsonl")))


if __name__ == "__main__":
    main()
