"""工具注册与内置工具的测试。"""
from agentkernel.tools import builtin
from agentkernel.tools.registry import Registry


def _make_registry():
    r = Registry()
    builtin.register_builtin(r)
    return r


def test_builtin_registered():
    r = _make_registry()
    assert "get_current_time" in r.names()
    assert "calculator" in r.names()


def test_calculator_ok():
    r = _make_registry()
    assert "56088" in r.run("calculator", {"expression": "123*456"})


def test_calculator_division_float():
    r = _make_registry()
    assert "2.5" in r.run("calculator", {"expression": "5/2"})


def test_calculator_missing_param():
    r = _make_registry()
    out = r.run("calculator", {})
    assert "参数" in out


def test_calculator_rejects_code():
    r = _make_registry()
    out = r.run("calculator", {"expression": "__import__('os').system('ls')"})
    assert "错误" in out


def test_unknown_tool():
    r = _make_registry()
    assert "未注册" in r.run("nope", {})


def test_current_time_format():
    import re
    r = _make_registry()
    out = r.run("get_current_time", {})
    assert re.match(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}", out)
