"""测试用 LLM 客户端：把调用委托给 canonical adapter。

这样测试 monkeypatch adapter.chat，同时 Agent 只依赖注入的端口对象。
"""

from __future__ import annotations

from typing import Any

from agentkernel.utils.observability import Usage


class RuntimeLLMClient:
    def chat(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.3,
        max_tokens: int | None = None,
    ) -> str:
        from agentkernel.adapters.llm import openai_compatible as llm

        return llm.chat(messages)

    def pop_usage(self) -> Usage | None:
        from agentkernel.adapters.llm import openai_compatible as llm

        return llm.pop_usage()

    def last_model(self) -> str | None:
        from agentkernel.adapters.llm import openai_compatible as llm

        return llm.last_model()


class RecordingLLMClient:
    def __init__(self, reply: str = "ok") -> None:
        self.reply = reply
        self.calls: list[list[dict[str, str]]] = []
        self.budgets: list[dict[str, Any]] = []

    def chat(self, messages: list[dict[str, str]], **kwargs: Any) -> str:
        self.calls.append(messages)
        self.budgets.append(kwargs)
        return self.reply

    def pop_usage(self) -> Usage | None:
        return None

    def last_model(self) -> str | None:
        return "fake-model"
