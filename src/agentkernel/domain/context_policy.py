"""上下文策略纯函数（A7.2）：不碰 I/O、不调模型。

Agent 只通过这些函数做截断/保留最近消息；compact 的模型调用在
application/context.py 的 ContextManager 中。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ContextConfig:
    """上下文管理配置（字符预算，避免引入 tokenizer 依赖）。"""

    max_history_chars: int = 8000
    compact_trigger_chars: int = 6000
    keep_recent_chars: int = 2000


def char_count(messages: list[dict[str, str]]) -> int:
    return sum(len(message["content"]) for message in messages)


def truncate_history(history: list[dict[str, str]], max_history_chars: int) -> list[dict[str, str]]:
    """固定首条用户消息（原始要求），其余从后往前保留最近消息。"""
    if not history:
        return []
    first_user = history[0] if history[0]["role"] == "user" else None
    budget = max_history_chars - (len(first_user["content"]) if first_user else 0)
    recent: list[dict[str, str]] = []
    used = 0
    for message in reversed(history[1:] if first_user else history):
        need = len(message["content"])
        if used + need > budget:
            break
        recent.append(message)
        used += need
    recent.reverse()

    if first_user is None:
        return recent
    if recent and recent[0] is first_user:
        return recent
    return [first_user] + recent


def recent_messages(history: list[dict[str, str]], keep_recent_chars: int) -> list[dict[str, str]]:
    recent: list[dict[str, str]] = []
    used = 0
    for message in reversed(history):
        need = len(message["content"])
        if used + need > keep_recent_chars and recent:
            break
        recent.append(message)
        used += need
    recent.reverse()
    return recent


def format_for_compact(messages: list[dict[str, str]]) -> str:
    return "\n".join(f"{message['role']}: {message['content']}" for message in messages)
