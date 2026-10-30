"""上下文编排（A7.2）：纯策略 + 可选 LLM 摘要压缩。"""

from __future__ import annotations

from agentkernel.domain.context_policy import (
    ContextConfig,
    char_count,
    format_for_compact,
    recent_messages,
    truncate_history,
)
from agentkernel.ports.llm import LLMClient

COMPACT_PROMPT = """请把下面的对话历史压缩成一段 200 字以内的中文摘要，保留：
1. 用户最初的要求和约束；
2. 已经完成的工具调用与关键结果；
3. 尚未完成的事项。

对话历史：
{history}

只输出摘要本身，不要输出其他内容。"""


class ContextManager:
    """按字符预算准备送入模型的历史；compact 失败时降级 truncate。"""

    def __init__(self, config: ContextConfig, llm_client: LLMClient) -> None:
        self.config = config
        self.llm_client = llm_client

    def prepare(self, history: list[dict[str, str]]) -> list[dict[str, str]]:
        if char_count(history) <= self.config.max_history_chars:
            return history
        if char_count(history) > self.config.compact_trigger_chars:
            compacted = self._try_compact(history)
            if compacted is not None and char_count(compacted) <= self.config.max_history_chars:
                return compacted
        return truncate_history(history, self.config.max_history_chars)

    def _try_compact(self, history: list[dict[str, str]]) -> list[dict[str, str]] | None:
        if len(history) < 2:
            return None
        recent = recent_messages(history, self.config.keep_recent_chars)
        older = history[: len(history) - len(recent)]
        if not older:
            return recent
        try:
            prompt = COMPACT_PROMPT.replace("{history}", format_for_compact(older))
            summary = self.llm_client.chat([{"role": "user", "content": prompt}]).strip()
        except Exception:
            return None
        if not summary:
            return None
        return [{"role": "user", "content": f"[对话摘要] {summary}"}] + recent
