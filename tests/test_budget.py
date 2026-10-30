"""G-25 会话预算：单轮工具调用上限与会话 token 上限（S8 可控制）。"""

from __future__ import annotations

from agentkernel.runtime.agent import Agent
from agentkernel.tools import builtin
from agentkernel.tools.registry import Registry


def _make_agent(**kwargs) -> Agent:
    registry = Registry()
    builtin.register_builtin(registry)
    return Agent(registry, max_steps=5, **kwargs)


def test_tool_call_budget_stops_turn(monkeypatch):
    monkeypatch.setattr(
        "agentkernel.runtime.llm.chat",
        lambda messages: '{"action": "calculator", "action_input": {"expression": "1+1"}}',
    )
    seen: list[str] = []
    events: list[dict] = []
    agent = _make_agent(max_tool_calls_per_turn=1)
    agent.on_tool_call = lambda name, args, result: seen.append(name)
    agent.on_event = events.append
    out = agent.run("一直算", [])
    assert "工具调用超过上限" in out
    assert seen == ["calculator"]
    assert any(
        e.get("event") == "budget_exceeded" and e.get("error_type") == "ToolCallBudget"
        for e in events
    )


def test_session_token_budget_stops_before_llm_call(monkeypatch):
    def _boom(messages):
        raise AssertionError("超预算后不应再调用 LLM")

    monkeypatch.setattr("agentkernel.runtime.llm.chat", _boom)
    events: list[dict] = []
    agent = _make_agent(session_token_budget=100)
    agent.session_tokens = 100
    agent.on_event = events.append
    out = agent.run("继续", [])
    assert "token 预算" in out
    assert any(e.get("error_type") == "TokenBudget" for e in events)


def test_budget_defaults_from_env(monkeypatch):
    monkeypatch.setenv("AGENTKERNEL_MAX_SESSION_TOKENS", "7")
    monkeypatch.setenv("AGENTKERNEL_MAX_TOOL_CALLS_PER_TURN", "2")
    agent = _make_agent()
    assert agent.session_token_budget == 7
    assert agent.max_tool_calls_per_turn == 2


def test_budget_disabled_by_zero(monkeypatch):
    monkeypatch.setattr(
        "agentkernel.runtime.llm.chat",
        lambda messages: '{"action": "final_answer", "action_input": "ok"}',
    )
    agent = _make_agent(session_token_budget=0, max_tool_calls_per_turn=0)
    assert agent.run("hi", []) == "ok"
