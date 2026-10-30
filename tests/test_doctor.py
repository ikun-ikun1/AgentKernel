"""G-36：make doctor 的 7 项体检（不依赖真实 MySQL）。"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load_doctor():
    spec = importlib.util.spec_from_file_location(
        "doctor_under_test", ROOT / "scripts" / "doctor.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclass 需要模块已注册
    spec.loader.exec_module(module)
    return module


doctor = _load_doctor()


def test_migration_heads_from_repo() -> None:
    assert doctor.migration_heads() == {"0002_tool_log_duration"}


def test_migration_verdict() -> None:
    heads = {"0002_tool_log_duration"}
    assert doctor.migration_verdict("0002_tool_log_duration", heads).status == "PASS"
    assert doctor.migration_verdict("0001_initial", heads).status == "FAIL"
    assert doctor.migration_verdict(None, heads).status == "FAIL"
    assert doctor.migration_verdict("x", set()).status == "FAIL"


def test_env_file_permissions(tmp_path: Path) -> None:
    assert doctor.check_env_file(tmp_path).status == "WARN"
    env = tmp_path / ".env"
    env.write_text("DEEPSEEK_API_KEY=sk-test\n", encoding="utf-8")
    env.chmod(0o600)
    assert doctor.check_env_file(tmp_path).status == "PASS"
    env.chmod(0o644)
    assert doctor.check_env_file(tmp_path).status == "FAIL"


def test_default_password_detection() -> None:
    assert doctor.check_default_password("sqlite:///:memory:").status == "WARN"
    weak = "mysql+pymysql://agentkernel:password@127.0.0.1:3306/db"
    assert doctor.check_default_password(weak).status == "FAIL"
    strong = "mysql+pymysql://agentkernel:Zx9%21LongPass@127.0.0.1:3306/db"
    assert doctor.check_default_password(strong).status == "PASS"


def test_cli_json_has_seven_checks() -> None:
    proc = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "doctor.py"),
            "--dsn",
            "sqlite:///:memory:",
            "--json",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    payload = json.loads(proc.stdout)
    assert payload["counts"]["FAIL"] == 0
    assert len(payload["checks"]) == 7
    assert {c["name"] for c in payload["checks"]} == {
        "python",
        "env",
        "deps",
        "mysql",
        "migration",
        "password",
        "disk",
    }


def test_cli_strict_fails_on_warn() -> None:
    proc = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "doctor.py"),
            "--dsn",
            "sqlite:///:memory:",
            "--strict",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 2, proc.stdout + proc.stderr
