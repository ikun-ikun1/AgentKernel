"""工具调用协议契约（借鉴 OpenClaw tool-call-repair 的 contracts.ts）。

定义合法的工具调用 JSON 结构：
  {"action": "工具名", "action_input": {...}}
  {"action": "final_answer", "action_input": "文本"}

OpenClaw 的关键思路：模型输出先按契约分类，只有「名字在允许清单里、
payload 是合法对象」的调用才被晋升为结构化工具调用；其余一律当普通文本处理。
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Iterable, Union

FINAL_ACTION = "final_answer"


@dataclass
class ToolCall:
    """模型输出的工具调用。"""
    action: str
    action_input: dict[str, Any]


@dataclass
class FinalAnswer:
    """最终回答。"""
    text: str


# 解析结果：工具调用 或 最终回答
Action = Union[ToolCall, FinalAnswer]


def classify(
    obj: dict[str, Any],
    allowed_actions: Iterable[str] | None = None,
) -> Action | None:
    """把解析出的 JSON dict 分类成 ToolCall / FinalAnswer，不合法返回 None。

    allowed_actions 不为空时，工具调用必须命中清单（OpenClaw 的 tool-name allowlist）；
    `final_answer` 始终允许，不受清单限制。
    """
    action = obj.get("action")
    if action == FINAL_ACTION:
        text = obj.get("action_input", "")
        return FinalAnswer(text=str(text) if text is not None else "")

    if isinstance(action, str) and action:
        if allowed_actions is not None and action not in set(allowed_actions):
            return None
        ai = obj.get("action_input")
        if not isinstance(ai, dict):
            return None
        return ToolCall(action=action, action_input=ai)
    return None
