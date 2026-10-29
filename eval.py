"""AgentKernel 评估脚本：一键跑分。

用法：
    python eval.py            # mock 模式（无需 API Key，验证内核逻辑，5 用例）
    python eval.py --live     # 真实 DeepSeek API + 解析层坏 JSON 用例（5 用例）

用例对应里程碑验收：
    1. 正常问答（final_answer 直出）
    2. 工具调用（calculator 被调用并回灌观察）
    3. 坏 JSON 修复（仅 mock：单引号/带噪声 JSON 不崩）
    4. 知识库问答（走 MCP knowledge_query，回答带来源）
    5. 上下文保持（第 2 轮还记得第 1 轮要求）
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from agentkernel.mcp.client import InProcessMCPClient, register_mcp_tools
from agentkernel.mcp.server import KnowledgeMCPServer
from agentkernel.rag.ingest import KnowledgeBase
from agentkernel.runtime.agent import Agent
from agentkernel.tools import builtin, contracts, json_repair
from agentkernel.tools.registry import Registry


class MockLLM:
    """按顺序吐出脚本化模型输出，记录每轮收到的 messages 供断言使用。"""

    def __init__(self, responses: list[str]) -> None:
        self.responses = list(responses)
        self.calls: list[list[dict[str, str]]] = []

    def __call__(self, messages: list[dict[str, str]]) -> str:
        self.calls.append(messages)
        if not self.responses:
            return '{"action": "final_answer", "action_input": "（mock 脚本耗尽）"}'
        return self.responses.pop(0)


def _build_agent() -> tuple[Agent, Registry]:
    registry = Registry()
    builtin.register_builtin(registry)
    kb = KnowledgeBase()
    kb.ingest_text(
        "notes.md",
        "ReAct 是 Reasoning + Acting 的循环：思考 → 行动 → 观察 → 回复。"
        "AgentKernel 从零实现了 ReAct 主循环。",
    )
    server = KnowledgeMCPServer(kb)
    client = InProcessMCPClient(server)
    register_mcp_tools(registry, client)
    return Agent(registry), registry


def run_mock_cases() -> list[dict[str, str]]:
    results: list[dict[str, str]] = []

    # 1. 正常问答
    mock = MockLLM(
        [
            '{"action": "final_answer", "action_input": "你好，我是 AgentKernel，一个从零实现的 Agent 内核。"}'
        ]
    )
    agent, _ = _build_agent()
    import agentkernel.runtime.agent as agent_module

    original_chat = agent_module.llm.chat
    agent_module.llm.chat = mock  # type: ignore[attr-defined]
    try:
        reply = agent.run("你好，请介绍一下你自己", [])
    finally:
        agent_module.llm.chat = original_chat  # type: ignore[attr-defined]
    results.append(
        {
            "case": "1. 正常问答",
            "pass": "AgentKernel" in reply,
            "detail": reply,
        }
    )

    # 2. 工具调用
    mock = MockLLM(
        [
            '{"action": "calculator", "action_input": {"expression": "123*456"}}',
            '{"action": "final_answer", "action_input": "结果是 56088"}',
        ]
    )
    agent, _ = _build_agent()
    agent_module.llm.chat = mock  # type: ignore[attr-defined]
    history: list[dict[str, str]] = []
    try:
        reply = agent.run("帮我算 123*456", history)
    finally:
        agent_module.llm.chat = original_chat  # type: ignore[attr-defined]
    tool_observed = any("工具 calculator 返回" in m["content"] for m in history)
    results.append(
        {
            "case": "2. 工具调用",
            "pass": "56088" in reply and tool_observed,
            "detail": reply,
        }
    )

    # 3. 坏 JSON 修复（单引号 + 带噪声）
    mock = MockLLM(["好的，结果如下：{'action': 'final_answer', 'action_input': '修复成功'}"])
    agent, _ = _build_agent()
    agent_module.llm.chat = mock  # type: ignore[attr-defined]
    try:
        reply = agent.run("故意输出坏 JSON", [])
    finally:
        agent_module.llm.chat = original_chat  # type: ignore[attr-defined]
    results.append(
        {
            "case": "3. 坏 JSON 修复",
            "pass": reply == "修复成功",
            "detail": reply,
        }
    )

    # 4. 知识库问答（走 MCP knowledge_query）
    mock = MockLLM(
        [
            '{"action": "knowledge_query", "action_input": {"query": "ReAct 是什么"}}',
            '{"action": "final_answer", "action_input": "ReAct 是思考-行动-观察循环，详见来源 notes.md"}',
        ]
    )
    agent, _ = _build_agent()
    agent_module.llm.chat = mock  # type: ignore[attr-defined]
    history = []
    try:
        reply = agent.run("什么是 ReAct？", history)
    finally:
        agent_module.llm.chat = original_chat  # type: ignore[attr-defined]
    has_source = any("来源：notes.md" in m["content"] for m in history)
    results.append(
        {
            "case": "4. 知识库问答",
            "pass": "notes.md" in reply and has_source,
            "detail": reply,
        }
    )

    # 5. 上下文保持
    mock = MockLLM(
        [
            '{"action": "final_answer", "action_input": "好的，我记住了。"}',
            '{"action": "final_answer", "action_input": "你叫小明，喜欢蓝色。"}',
        ]
    )
    agent, _ = _build_agent()
    agent_module.llm.chat = mock  # type: ignore[attr-defined]
    history = []
    try:
        agent.run("记住：我叫小明，我喜欢蓝色。", history)
        reply = agent.run("我叫什么？", history)
    finally:
        agent_module.llm.chat = original_chat  # type: ignore[attr-defined]
    results.append(
        {
            "case": "5. 上下文保持",
            "pass": "小明" in reply and len(history) >= 4,
            "detail": reply,
        }
    )
    return results


def run_live_cases() -> list[dict[str, str]]:
    agent, _ = _build_agent()
    results: list[dict[str, str]] = []
    history: list[dict[str, str]] = []

    cases = [
        (
            "1. 正常问答",
            "用一句话介绍 AgentKernel（回答中必须包含 AgentKernel）",
            lambda r: "AgentKernel" in r,
        ),
        ("2. 工具调用", "帮我算 123*456", lambda r: "56088" in r),
        (
            "3. 知识库问答",
            "什么是 ReAct？",
            lambda r: "ReAct" in r and ("来源" in r or "notes.md" in r),
        ),
    ]
    for name, question, check in cases:
        try:
            reply = agent.run(question, history)
            passed = check(reply)
        except Exception as e:
            reply = f"错误：{type(e).__name__}: {e}"
            passed = False
        results.append({"case": name, "pass": passed, "detail": reply})

    # 4. 上下文保持（使用独立历史，确保测试的是「第 2 轮记得第 1 轮」）
    context_history: list[dict[str, str]] = []
    try:
        agent.run("先记住：我叫小明，我喜欢蓝色。", context_history)
        reply = agent.run("我叫什么？", context_history)
        passed = "小明" in reply
    except Exception as e:
        reply = f"错误：{type(e).__name__}: {e}"
        passed = False
    results.append({"case": "4. 上下文保持", "pass": passed, "detail": reply})

    # 5. 坏 JSON 修复（解析层，不调 API；真实模型不易故意输出坏 JSON）
    bad = "好的，结果如下：{'action': 'final_answer', 'action_input': '修复成功'}"
    action = json_repair.repair_action(bad)
    passed = isinstance(action, contracts.FinalAnswer) and action.text == "修复成功"
    results.append(
        {
            "case": "5. 坏 JSON 修复（解析层）",
            "pass": passed,
            "detail": "修复成功" if passed else str(action),
        }
    )
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="AgentKernel 评估脚本")
    parser.add_argument("--live", action="store_true", help="使用真实 DeepSeek API（默认 mock）")
    args = parser.parse_args()

    if args.live:
        results = run_live_cases()
    else:
        results = run_mock_cases()

    passed = 0
    print("=" * 60)
    print("AgentKernel 评估结果")
    print("=" * 60)
    for r in results:
        status = "PASS" if r["pass"] else "FAIL"
        print(f"[{status}] {r['case']}")
        print(f"       {r['detail'][:120]}")
        passed += int(r["pass"])
    print("=" * 60)
    print(f"通过 {passed}/{len(results)}")
    if passed != len(results):
        sys.exit(1)


if __name__ == "__main__":
    main()
