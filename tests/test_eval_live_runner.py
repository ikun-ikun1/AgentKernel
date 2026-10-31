"""P0-2 runner 的纯函数检查（不调用真实 API）。"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load():
    spec = importlib.util.spec_from_file_location(
        "eval_live_runner", ROOT / "scripts" / "eval_live.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


runner = _load()


def test_check_case_pass() -> None:
    case = {
        "expected_tools": ["calculator"],
        "expected_args": {"calculator": {"expression": "6*7"}},
        "must_contain": ["42"],
    }
    problems = runner._check_case(
        case,
        "42",
        ["calculator"],
        [("calculator", {"expression": "6 * 7"})],
        None,
    )
    assert problems == []


def test_check_case_reports_tool_and_answer() -> None:
    case = {"expected_tools": ["calculator"], "must_contain": ["42"]}
    problems = runner._check_case(case, "不知道", [], [], None)
    assert any(p.startswith("tool_selection") for p in problems)
    assert any(p.startswith("answer") for p in problems)


def test_check_case_forbidden_and_runtime() -> None:
    case = {"expected_tools": [], "must_not_contain": ["sk-"]}
    problems = runner._check_case(case, "sk-secret", [], [], "Timeout")
    assert any(p.startswith("runtime") for p in problems)
    assert any(p.startswith("forbidden") for p in problems)


def test_p95_handles_single_and_empty() -> None:
    assert runner._p95([]) is None
    assert runner._p95([12.5]) == 12.5
