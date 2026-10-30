"""A7.1：Agent 必须使用注入的 LLMClient，而不是 runtime/llm shim。"""

from __future__ import annotations

from agentkernel.runtime.agent import Agent
from agentkernel.tools.registry import Registry
from tests.llm_client_stub import RecordingLLMClient


def test_agent_uses_injected_llm_client() -> None:
    fake = RecordingLLMClient(reply='{"action": "final_answer", "action_input": "injected-ok"}')
    agent = Agent(Registry(), llm_client=fake)
    assert agent.run("你好", []) == "injected-ok"
    assert len(fake.calls) == 1
    assert fake.calls[0][0]["role"] == "system"


def test_agent_does_not_touch_module_level_llm(monkeypatch) -> None:
    def boom(*args, **kwargs):
        raise AssertionError("Agent 不应调用 runtime.llm.chat")

    monkeypatch.setattr("agentkernel.adapters.llm.openai_compatible.chat", boom)
    fake = RecordingLLMClient(reply='{"action": "final_answer", "action_input": "port-only"}')
    agent = Agent(Registry(), llm_client=fake)
    assert agent.run("hi", []) == "port-only"
