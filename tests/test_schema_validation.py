"""JSON Schema 子集与工具调用契约的边界分支。"""

from __future__ import annotations

import pytest

from agentkernel.tools.contracts import FinalAnswer, ToolCall, ToolCalls, classify
from agentkernel.tools.registry import validate_parameters
from agentkernel.utils.errors import ToolParamError


def test_enum_violation() -> None:
    with pytest.raises(ToolParamError, match="必须是"):
        validate_parameters({"enum": ["a", "b"]}, "c")


def test_object_type_and_required() -> None:
    schema = {"type": "object", "required": ["x"], "properties": {"x": {"type": "string"}}}
    with pytest.raises(ToolParamError, match="必须是对象"):
        validate_parameters(schema, [])
    with pytest.raises(ToolParamError, match="缺少必填参数"):
        validate_parameters(schema, {})
    with pytest.raises(ToolParamError, match="参数.x 必须是字符串"):
        validate_parameters(schema, {"x": 1})


def test_additional_properties_false_rejects_extra() -> None:
    schema = {"type": "object", "additionalProperties": False, "properties": {"x": {}}}
    with pytest.raises(ToolParamError, match="含未允许字段"):
        validate_parameters(schema, {"x": 1, "y": 2})
    validate_parameters({"type": "object", "properties": {"x": {}}}, {"x": 1, "y": 2})


def test_numeric_and_boolean_types() -> None:
    with pytest.raises(ToolParamError, match="必须是整数"):
        validate_parameters({"type": "integer"}, True)
    with pytest.raises(ToolParamError, match="必须是数字"):
        validate_parameters({"type": "number"}, "1")
    validate_parameters({"type": "number"}, 1.5)
    with pytest.raises(ToolParamError, match="必须是布尔值"):
        validate_parameters({"type": "boolean"}, 1)


def test_array_items_and_null() -> None:
    with pytest.raises(ToolParamError, match="必须是数组"):
        validate_parameters({"type": "array"}, "x")
    with pytest.raises(ToolParamError, match=r"参数\[1\]"):
        validate_parameters({"type": "array", "items": {"type": "string"}}, ["a", 2])
    validate_parameters({"type": "null"}, None)
    with pytest.raises(ToolParamError, match="必须是 null"):
        validate_parameters({"type": "null"}, 0)


def test_schema_without_type_passes_anything() -> None:
    validate_parameters({}, {"anything": object()})


def test_classify_single_tool_and_rejections() -> None:
    assert isinstance(classify({"action": "calculator", "action_input": {}}), ToolCall)
    assert classify({"action": "calculator", "action_input": "x"}) is None
    assert classify({"action": "unknown", "action_input": {}}, {"calculator"}) is None
    assert classify({"action": "", "action_input": {}}) is None


def test_classify_final_answer_and_none_input() -> None:
    action = classify({"action": "final_answer", "action_input": None})
    assert isinstance(action, FinalAnswer) and action.text == ""
    assert isinstance(classify({"action": "final_answer"}), FinalAnswer)


def test_classify_multi_tool_edges() -> None:
    calls = classify(
        {"actions": [{"action": "a", "action_input": {}}, {"action": "b", "action_input": {}}]},
        {"a", "b"},
    )
    assert isinstance(calls, ToolCalls) and len(calls.calls) == 2
    assert classify({"actions": []}) is None
    assert classify({"actions": [1]}) is None
    assert classify({"actions": [{"action_input": {}}]}) is None
    assert classify({"actions": [{"action": "z", "action_input": {}}]}, {"a"}) is None
    assert classify({"actions": [{"action": "a", "action_input": []}]}, {"a"}) is None
