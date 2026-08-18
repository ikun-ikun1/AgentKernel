"""json_repair 三层修复的测试。"""
from agentkernel.tools import json_repair


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


def test_degrade_to_none():
    text = "我无法回答这个问题"
    assert json_repair.parse_json(text) is None
