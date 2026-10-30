"""兼容 shim：LLM 适配器已移到 adapters/llm/openai_compatible.py（A3）。

保留 chat/pop_usage/last_model 的模块级导出，供 Agent 与既有 monkeypatch 使用。
"""

from __future__ import annotations

from agentkernel.adapters.llm.openai_compatible import _get_client, chat, last_model, pop_usage

__all__ = ["_get_client", "chat", "last_model", "pop_usage"]
