"""LLM 端口（A3）：对话补全与 usage 读取的最小接口。

实现见 adapters/llm/openai_compatible.py；Agent 通过 runtime/llm.py 的兼容导出调用，
既保持 monkeypatch 契约，又不让 Agent 依赖 OpenAI SDK。
"""

from __future__ import annotations

from typing import Protocol

from agentkernel.utils.observability import Usage


class LLMClient(Protocol):
    def chat(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.3,
        max_tokens: int | None = None,
    ) -> str:
        """返回模型文本输出。"""
        ...

    def pop_usage(self) -> Usage | None:
        """取走并清空最近一次调用的 usage。"""
        ...

    def last_model(self) -> str | None:
        """最近一次调用使用的模型名。"""
        ...
