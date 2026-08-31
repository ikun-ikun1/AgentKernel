"""工具调用协议契约（借鉴 OpenClaw tool-call-repair 的 contracts.ts）。

定义合法的工具调用 JSON 结构：
  单工具：  {"action": "工具名", "action_input": {...}}
  多工具：  {"actions": [{"action": "...", "action_input": {...}}, ...]}
  最终回答：{"action": "final_answer", "action_input": "文本"}

OpenClaw 的关键思路：模型输出先按契约分类，只有「名字在允许清单里、
payload 是合法对象」的调用才被晋升为结构化工具调用；其余一律当普通文本处理。

多工具调用对应 agent-study Ch11「Parallel Tool Calling」：模型可一次输出多个
工具调用，当前内核按顺序执行（无依赖时也可并行，注释见 runtime/agent.py）。
"""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any, Union

FINAL_ACTION = "final_answer"


@dataclass
class ToolCall:
    """模型输出的单个工具调用。"""
    action: str
    action_input: dict[str, Any]


@dataclass
class ToolCalls:
    """模型一次输出的多个工具调用。"""
    calls: list[ToolCall]


@dataclass
class FinalAnswer:
    """最终回答。"""
    text: str


# 解析结果：单个工具调用 / 多个工具调用 / 最终回答
Action = Union[ToolCall, ToolCalls, FinalAnswer]


def _allowed(name: str, allowed_actions: set[str] | None) -> bool:
    return allowed_actions is None or name in allowed_actions


def classify(
    obj: dict[str, Any],
    allowed_actions: Iterable[str] | None = None,
) -> Action | None:
    """把解析出的 JSON dict 分类成 ToolCall / ToolCalls / FinalAnswer。

    allowed_actions 不为空时，工具调用必须命中清单（OpenClaw 的 tool-name allowlist）；
    `final_answer` 始终允许，不受清单限制。
    """
    allowed = set(allowed_actions) if allowed_actions is not None else None

    action = obj.get("action")
    if action == FINAL_ACTION:
        text = obj.get("action_input", "")
        return FinalAnswer(text=str(text) if text is not None else "")

    # 单工具调用：{"action": "...", "action_input": {...}}
    if isinstance(action, str) and action:
        if not _allowed(action, allowed):
            return None
        ai = obj.get("action_input")
        if not isinstance(ai, dict):
            return None
        return ToolCall(action=action, action_input=ai)

    # 多工具调用：{"actions": [{"action": "...", "action_input": {...}}, ...]}
    actions = obj.get("actions")
    if isinstance(actions, list) and actions:
        calls: list[ToolCall] = []
        for item in actions:
            if not isinstance(item, dict):
                return None
            name = item.get("action")
            if not isinstance(name, str) or not name:
                return None
            if not _allowed(name, allowed):
                return None
            ai = item.get("action_input")
            if not isinstance(ai, dict):
                return None
            calls.append(ToolCall(action=name, action_input=ai))
        return ToolCalls(calls=calls)
    return None
