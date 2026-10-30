"""json_repair 边界：转义引号、未闭合括号、非 dict 字面量、allowlist 细节。"""

from __future__ import annotations

from agentkernel.tools import json_repair as jr


def test_extract_braces_handles_escaped_quotes() -> None:
    raw = 'prefix {"a": "x\\"y"} suffix'
    assert jr._extract_braces(raw) == '{"a": "x\\"y"}'


def test_extract_braces_returns_none_when_unbalanced() -> None:
    assert jr._extract_braces('{"a": 1') is None
    assert jr._extract_braces("no json here") is None


def test_swap_quotes_only_returns_dicts() -> None:
    assert jr._swap_quotes("{'a': 1}") == {"a": 1}
    assert jr._swap_quotes("[1, 2]") is None
    assert jr._swap_quotes("{broken") is None


def test_actions_allowed_requires_string_action() -> None:
    allowed = {"calculator"}
    assert jr._actions_allowed({"actions": [{"action": "calculator"}]}, allowed) is True
    assert jr._actions_allowed({"actions": [{"action": 1}]}, allowed) is False
    assert jr._actions_allowed({"actions": "not-a-list"}, allowed) is False
    assert jr._actions_allowed({}, allowed) is False


def test_parse_json_rejects_non_dict_and_oversize() -> None:
    assert jr.parse_json("[1, 2]") is None
    assert jr.parse_json('{"a": 1}', max_payload_bytes=4) is None
