"""ReAct 主循环与上下文管理的测试（用 fake LLM，不依赖真实 API）。"""
from __future__ import annotations

from agentkernel.runtime.agent import Agent, ContextConfig
from agentkernel.tools import builtin
from agentkernel.tools.registry import Registry


def _make_agent(max_steps: int = 5, context: ContextConfig | None = None) -> Agent:
    registry = Registry()
    builtin.register_builtin(registry)
    return Agent(registry, max_steps=max_steps, context=context)


def test_final_answer_direct(monkeypatch):
    monkeypatch.setattr(
        "agentkernel.runtime.llm.chat",
        lambda messages: '{"action": "final_answer", "action_input": "你好"}',
    )
    agent = _make_agent()
    history: list[dict[str, str]] = []
    assert agent.run("你好", history) == "你好"
    assert history[0] == {"role": "user", "content": "你好"}
    assert history[-1] == {"role": "assistant", "content": "你好"}


def test_tool_call_then_answer(monkeypatch):
    outputs = iter(
        [
            '{"action": "calculator", "action_input": {"expression": "1+2"}}',
            '{"action": "final_answer", "action_input": "3"}',
        ]
    )
    monkeypatch.setattr("agentkernel.runtime.llm.chat", lambda messages: next(outputs))
    agent = _make_agent()
    history: list[dict[str, str]] = []
    assert agent.run("1+2 等于几", history) == "3"
    assert any("工具 calculator 返回" in m["content"] for m in history)
    assert any("3" in m["content"] for m in history)


def test_multi_tool_call_executes_all_then_answers(monkeypatch):
    outputs = iter(
        [
            '{"actions": ['
            '{"action": "calculator", "action_input": {"expression": "1+2"}}, '
            '{"action": "calculator", "action_input": {"expression": "4*5"}}]}',
            '{"action": "final_answer", "action_input": "分别是 3 和 20"}',
        ]
    )
    monkeypatch.setattr("agentkernel.runtime.llm.chat", lambda messages: next(outputs))
    seen: list[str] = []
    agent = _make_agent()
    agent.on_tool_call = lambda name, args, result: seen.append(name)
    history: list[dict[str, str]] = []
    assert agent.run("算两个数", history) == "分别是 3 和 20"
    assert seen == ["calculator", "calculator"]
    assert (
        sum(
            1
            for m in history
            if m["role"] == "user" and "工具 calculator 返回" in m["content"]
        )
        == 2
    )


def test_tool_observer_receives_tool_calls(monkeypatch):
    outputs = iter(
        [
            '{"action": "calculator", "action_input": {"expression": "1+2"}}',
            '{"action": "final_answer", "action_input": "3"}',
        ]
    )
    monkeypatch.setattr("agentkernel.runtime.llm.chat", lambda messages: next(outputs))
    seen: list[tuple[str, dict, str]] = []
    agent = _make_agent()
    agent.on_tool_call = lambda name, args, result: seen.append((name, args, result))
    agent.run("1+2 等于几", [])
    assert len(seen) == 1
    assert seen[0][0] == "calculator"
    assert seen[0][1] == {"expression": "1+2"}
    assert "3" in seen[0][2]


def test_bad_json_degrades_to_plain_text(monkeypatch):
    raw = "我算不出来"
    monkeypatch.setattr("agentkernel.runtime.llm.chat", lambda messages: raw)
    agent = _make_agent()
    history: list[dict[str, str]] = []
    assert agent.run("帮我算一下", history) == raw
    assert history[-1]["content"] == raw


def test_unregistered_tool_is_not_called(monkeypatch):
    raw = '{"action": "dangerous_tool", "action_input": {}}'
    monkeypatch.setattr("agentkernel.runtime.llm.chat", lambda messages: raw)
    agent = _make_agent()
    history: list[dict[str, str]] = []
    # 未注册工具命中 allowlist 过滤 → 降级为纯文本，不执行
    assert agent.run("做点危险的事", history) == raw


def test_max_steps_guard(monkeypatch):
    monkeypatch.setattr(
        "agentkernel.runtime.llm.chat",
        lambda messages: '{"action": "get_current_time", "action_input": {}}',
    )
    agent = _make_agent(max_steps=3)
    history: list[dict[str, str]] = []
    assert agent.run("现在几点", history) == "（达到最大步数上限，未完成）"


def test_context_truncate_keeps_first_user_message(monkeypatch):
    # 让 compact 失败，强制走 truncate 路径，保证测试确定性（不依赖真实 API）
    def boom(messages):
        raise RuntimeError("模型不可用")

    monkeypatch.setattr("agentkernel.runtime.llm.chat", boom)
    context = ContextConfig(max_history_chars=100, compact_trigger_chars=60, keep_recent_chars=40)
    agent = _make_agent(context=context)
    history = [{"role": "user", "content": "记住：我叫小明，我喜欢蓝色。"}]
    history += [{"role": "assistant", "content": "好的，我记住了。"}] * 20
    history.append({"role": "user", "content": "我叫什么？"})
    prepared = agent._prepare_history(history)
    assert prepared[0]["content"] == "记住：我叫小明，我喜欢蓝色。"
    assert prepared[-1]["content"] == "我叫什么？"
    assert sum(len(m["content"]) for m in prepared) <= context.max_history_chars


def test_context_compact_falls_back_to_truncate_when_llm_fails(monkeypatch):
    def boom(messages):
        raise RuntimeError("模型不可用")

    monkeypatch.setattr("agentkernel.runtime.llm.chat", boom)
    context = ContextConfig(max_history_chars=40, compact_trigger_chars=30, keep_recent_chars=20)
    agent = _make_agent(context=context)
    history = [{"role": "user", "content": "记住：我叫小明。"}] + [
        {"role": "assistant", "content": "好的。"}
    ] * 30
    prepared = agent._prepare_history(history)
    assert prepared[0]["content"] == "记住：我叫小明。"
    assert len(prepared) < len(history)


def test_context_compact_uses_summary(monkeypatch):
    def fake_chat(messages):
        # 第一次调用是 compact 摘要，第二次调用是正常回答
        return "用户叫小明"

    monkeypatch.setattr("agentkernel.runtime.llm.chat", fake_chat)
    context = ContextConfig(max_history_chars=40, compact_trigger_chars=30, keep_recent_chars=20)
    agent = _make_agent(context=context)
    history = [{"role": "user", "content": "记住：我叫小明，我喜欢蓝色。"}] + [
        {"role": "assistant", "content": "好的。"}
    ] * 30
    prepared = agent._prepare_history(history)
    assert prepared[0]["content"] == "[对话摘要] 用户叫小明"
    assert prepared[0]["role"] == "user"
