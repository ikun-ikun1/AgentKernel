"""json_repair 三层修复的测试。"""
from agentkernel.tools import contracts, json_repair


def test_parse_clean_json():
    text = '{"action": "get_current_time", "action_input": {}}'
    assert json_repair.parse_json(text) == {"action": "get_current_time", "action_input": {}}


def test_extract_with_noise():
    text = '好的，我来查一下：{"action": "calculator", "action_input": {"expression": "1+2"}} 就是这样'
    assert json_repair.parse_json(text)["action"] == "calculator"


def test_code_fence_and_trailing_comma():
    text = '```json\n{"action": "calculator", "action_input": {"expression": "1+2",},}\n```'
    obj = json_repair.parse_json(text)
    assert obj["action"] == "calculator"
    assert obj["action_input"]["expression"] == "1+2"


def test_single_quotes():
    text = "{'action': 'get_current_time', 'action_input': {}}"
    assert json_repair.parse_json(text)["action"] == "get_current_time"


def test_single_quotes_preserve_apostrophe_in_value():
    text = "{'action': 'final_answer', 'action_input': \"it's fine\"}"
    assert json_repair.parse_json(text)["action_input"] == "it's fine"


def test_degrade_to_none():
    text = "我无法回答这个问题"
    assert json_repair.parse_json(text) is None


def test_allowlist_filters_unregistered_action():
    text = '{"action": "dangerous", "action_input": {}}'
    assert json_repair.parse_json(text, allowed_actions={"calculator"}) is None
    assert json_repair.parse_json(text) is not None  # 不加清单时不拦截


def test_allowlist_allows_final_answer():
    text = '{"action": "final_answer", "action_input": "你好"}'
    assert json_repair.parse_json(text, allowed_actions={"calculator"}) is not None


def test_payload_byte_limit():
    text = '{"action": "calculator", "action_input": {"expression": "1+2"}}'
    assert json_repair.parse_json(text, max_payload_bytes=1000) is not None
    assert json_repair.parse_json(text, max_payload_bytes=5) is None


def test_repair_action_classifies_tool_call():
    action = json_repair.repair_action(
        '{"action": "calculator", "action_input": {"expression": "1+2"}}',
        allowed_actions={"calculator"},
    )
    assert isinstance(action, contracts.ToolCall)
    assert action.action == "calculator"


def test_repair_action_rejects_non_dict_input():
    assert (
        json_repair.repair_action(
            '{"action": "calculator", "action_input": "1+2"}',
            allowed_actions={"calculator"},
        )
        is None
    )


def test_parse_and_classify_multi_actions():
    text = (
        '{"actions": [{"action": "calculator", "action_input": {"expression": "1+2"}}, '
        '{"action": "get_current_time", "action_input": {}}]}'
    )
    action = json_repair.repair_action(
        text, allowed_actions={"calculator", "get_current_time"}
    )
    assert isinstance(action, contracts.ToolCalls)
    assert len(action.calls) == 2
    assert action.calls[0].action == "calculator"


def test_allowlist_filters_multi_actions():
    text = (
        '{"actions": [{"action": "calculator", "action_input": {}}, '
        '{"action": "dangerous", "action_input": {}}]}'
    )
    assert json_repair.parse_json(text, allowed_actions={"calculator"}) is None
