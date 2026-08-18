"""非法 JSON 三层修复（借鉴 OpenClaw tool-call-repair 的 grammar/payload/promote 分层）。

1. 提取（payload）：从文本里抠出第一个平衡的 { ... } 片段
2. 修复（promote）：去代码围栏、去尾逗号、单引号换双引号，升级为合法 JSON
3. 降级：都失败 → 返回 None，调用方把原始输出当普通回复
"""
from __future__ import annotations
import json
import re
from typing import Any, Optional


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


def parse_json(text: str) -> Optional[dict[str, Any]]:
    """三层修复入口。返回解析出的 dict，无法修复返回 None（降级为纯文本）。"""
    frag = _extract_braces(text)
    if frag is None:
        return None

    candidates = [
        frag,
        _remove_trailing_commas(_strip_fences(frag)),
        _swap_quotes(_remove_trailing_commas(_strip_fences(frag))),
    ]
    for candidate in candidates:
        try:
            obj = json.loads(candidate)
            if isinstance(obj, dict):
                return obj
        except (json.JSONDecodeError, ValueError):
            continue
    return None
