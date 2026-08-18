"""工具调用协议契约（借鉴 OpenClaw tool-call-repair 的 contracts.ts）。

定义合法的工具调用 JSON 结构：
  {"action": "工具名", "action_input": {...}}
  {"action": "final_answer", "action_input": "文本"}
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Union

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


def classify(obj: dict[str, Any]) -> Action | None:
    """把解析出的 JSON dict 分类成 ToolCall / FinalAnswer，不合法返回 None。"""
    action = obj.get("action")
    if action == FINAL_ACTION:
        return FinalAnswer(text=str(obj.get("action_input", "")))
    if isinstance(action, str) and action:
        ai = obj.get("action_input")
        if not isinstance(ai, dict):
            ai = {}
        return ToolCall(action=action, action_input=ai)
    return None
