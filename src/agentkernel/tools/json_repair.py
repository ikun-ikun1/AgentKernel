"""非法 JSON 三层修复（借鉴 OpenClaw tool-call-repair 的 grammar/payload/promote 分层）。

分层职责：
1. 提取（payload）：从模型文本里抠出第一个平衡的 `{ ... }` 片段，正确处理字符串内的括号。
2. 修复（promote）：去代码围栏、去尾逗号、单引号换双引号，逐层尝试升级为合法 JSON。
3. 降级：都失败 → 返回 None，调用方把原始输出当普通回复。

与 OpenClaw 对齐的增强点：
- `allowed_actions` 工具名允许清单：只有已注册工具才会被修复/晋升，未注册工具一律降级。
- `max_payload_bytes` payload 上限：超过 256KB 的候选直接放弃，防止把长正文误判成工具调用。
- `repair_action` 一步完成「修复 + 契约分类」，是 OpenClaw `promote` 的 Python 简化版。
"""
from __future__ import annotations
import json
import re
from typing import Any, Optional

from agentkernel.tools import contracts

DEFAULT_MAX_PAYLOAD_BYTES = 256_000


def _extract_braces(text: str) -> Optional[str]:
    """第 1 层：提取第一个平衡的 { ... } 片段（正确处理字符串内的括号）。"""
    start = text.find("{")
    if start == -1:
        return None
    depth = 0
    in_str = False
    esc = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return None


def _strip_fences(s: str) -> str:
    """去代码围栏 ```json ... ```。"""
    return re.sub(r"^```[a-zA-Z]*\s*|\s*```$", "", s.strip())


def _remove_trailing_commas(s: str) -> str:
    """去尾逗号：{...,} / [...,] 。"""
    return re.sub(r",\s*([}\]])", r"\1", s)


def _swap_quotes(s: str) -> str:
    """单引号换双引号（简单场景的 last resort）。"""
    return s.replace("'", '"')


def _within_payload_limit(frag: str, max_payload_bytes: int) -> bool:
    return len(frag.encode("utf-8")) <= max_payload_bytes


def parse_json(
    text: str,
    *,
    allowed_actions: Optional[set[str] | frozenset[str]] = None,
    max_payload_bytes: int = DEFAULT_MAX_PAYLOAD_BYTES,
) -> Optional[dict[str, Any]]:
    """三层修复入口。返回解析出的 dict，无法修复返回 None（降级为纯文本）。

    allowed_actions 用于在解析成功后立即做名字允许清单过滤；
    未命中清单的 dict 视为修复失败（调用方降级处理）。
    """
    frag = _extract_braces(text)
    if frag is None or not _within_payload_limit(frag, max_payload_bytes):
        return None

    candidates = [
        frag,
        _remove_trailing_commas(_strip_fences(frag)),
        _swap_quotes(_remove_trailing_commas(_strip_fences(frag))),
    ]
    for candidate in candidates:
        try:
            obj = json.loads(candidate)
        except (json.JSONDecodeError, ValueError):
            continue
        if not isinstance(obj, dict):
            continue
        if allowed_actions is not None and not _actions_allowed(obj, allowed_actions):
            return None
        return obj
    return None


def _actions_allowed(
    obj: dict[str, Any], allowed_actions: set[str] | frozenset[str]
) -> bool:
    """允许清单过滤：单工具看 action，多工具看 actions 数组每一项。"""
    action = obj.get("action")
    if action == contracts.FINAL_ACTION:
        return True
    if isinstance(action, str):
        return action in allowed_actions
    actions = obj.get("actions")
    if isinstance(actions, list):
        return all(
            isinstance(item, dict)
            and isinstance(item.get("action"), str)
            and item["action"] in allowed_actions
            for item in actions
        )
    return False


def repair_action(
    text: str,
    *,
    allowed_actions: Optional[set[str] | frozenset[str]] = None,
    max_payload_bytes: int = DEFAULT_MAX_PAYLOAD_BYTES,
) -> Optional[contracts.Action]:
    """OpenClaw `promote` 的 Python 简化版：修复 + 契约分类一步完成。

    失败返回 None，调用方应把原始文本当普通回复展示。
    """
    obj = parse_json(
        text,
        allowed_actions=allowed_actions,
        max_payload_bytes=max_payload_bytes,
    )
    if obj is None:
        return None
    return contracts.classify(obj, allowed_actions=allowed_actions)
