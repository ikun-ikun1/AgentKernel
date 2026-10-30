"""P0-5 安全边界测试：MCP profile、路径白名单、env 清洗、DSN 脱敏。"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest

from agentkernel.mcp import profiles as prof
from agentkernel.rag.knowledge import KnowledgeBase
from agentkernel.utils import observability as obs
from agentkernel.utils import paths as path_utils


def _exe(name: str) -> Path:
    found = shutil.which(name)
    assert found, f"环境缺少 {name}"
    return Path(found).resolve()


def _current_interpreter() -> Path:
    """用当前解释器测解释器白名单：CI 上不一定有 python3.11 这个命令名。"""
    return Path(sys.executable).resolve()


def _profile_file(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "mcp_profiles.toml"
    path.write_text(body, encoding="utf-8")
    return path


def test_profile_exact_argv_and_env(tmp_path: Path) -> None:
    exe = _exe("true")
    cfg = _profile_file(
        tmp_path,
        f"""[[mcp_profiles]]
name = "t"
command = "{exe}"
args = ["--flag", "value"]
env_allowlist = ["PATH"]
""",
    )
    profiles = prof.load_profiles(cfg)
    assert profiles["t"].args == ("--flag", "value")

    env = prof.build_child_env(
        profiles["t"], source={"PATH": "/bin", "DEEPSEEK_API_KEY": "sk-x", "HOME": "/root"}
    )
    assert env == {"PATH": "/bin"}


def test_versioned_python_counts_as_interpreter() -> None:
    assert prof.is_interpreter_command("python3.11")
    assert prof.is_interpreter_command("python3.12")
    assert prof.is_interpreter_command("python")
    assert prof.is_interpreter_command("pypy3")
    assert not prof.is_interpreter_command("echo")


def test_interpreter_requires_explicit_flag(tmp_path: Path) -> None:
    python = _current_interpreter()
    cfg = _profile_file(
        tmp_path,
        f"""[[mcp_profiles]]
name = "py"
command = "{python}"
args = ["-c", "print(1)"]
""",
    )
    with pytest.raises(prof.McpProfileError, match="allow_interpreter"):
        prof.load_profiles(cfg)


def test_interpreter_allowed_when_declared(tmp_path: Path) -> None:
    python = _current_interpreter()
    cfg = _profile_file(
        tmp_path,
        f"""[[mcp_profiles]]
name = "py"
command = "{python}"
allow_interpreter = true
args = ["-c", "print(1)"]
""",
    )
    assert prof.load_profiles(cfg)["py"].allow_interpreter is True


def test_relative_command_rejected(tmp_path: Path) -> None:
    cfg = _profile_file(
        tmp_path,
        """[[mcp_profiles]]
name = "bad"
command = "echo"
""",
    )
    with pytest.raises(prof.McpProfileError, match="绝对路径"):
        prof.load_profiles(cfg)


def test_unknown_profile_rejected(tmp_path: Path) -> None:
    cfg = _profile_file(tmp_path, "")
    with pytest.raises(prof.McpProfileError, match="未声明"):
        prof.select_profile("nope", prof.load_profiles(cfg))


def test_env_never_leaks_secrets() -> None:
    profile = prof.McpProfile(name="x", command="/bin/true")
    env = prof.build_child_env(
        profile,
        source={
            "PATH": "/bin",
            "DEEPSEEK_API_KEY": "sk-x",
            "AGENTKERNEL_DB_URL": "mysql://u:p@h/db",
            "OPENAI_API_KEY": "sk-y",
            "AWS_SECRET_ACCESS_KEY": "z",
        },
    )
    assert env == {"PATH": "/bin"}


def test_path_inside_root_ok(tmp_path: Path) -> None:
    root = tmp_path / "docs"
    root.mkdir()
    file = root / "a.md"
    file.write_text("hi", encoding="utf-8")
    assert path_utils.ensure_within(file, [root.resolve()]) == file.resolve()


def test_path_traversal_rejected(tmp_path: Path) -> None:
    root = tmp_path / "docs"
    root.mkdir()
    outside = tmp_path / "secret.md"
    outside.write_text("x", encoding="utf-8")
    with pytest.raises(path_utils.PathBoundaryError, match="不在允许的根目录"):
        path_utils.ensure_within(root / ".." / "secret.md", [root.resolve()])


def test_symlink_file_escape_rejected(tmp_path: Path) -> None:
    root = tmp_path / "docs"
    root.mkdir()
    outside = tmp_path / "secret.md"
    outside.write_text("x", encoding="utf-8")
    link = root / "link.md"
    link.symlink_to(outside)
    with pytest.raises(path_utils.PathBoundaryError, match="不在允许的根目录"):
        path_utils.ensure_within(link, [root.resolve()])


def test_symlink_dir_not_traversed(tmp_path: Path) -> None:
    root = tmp_path / "docs"
    root.mkdir()
    (root / "real.md").write_text("ok", encoding="utf-8")
    outside_dir = tmp_path / "outside"
    outside_dir.mkdir()
    (outside_dir / "leak.md").write_text("secret", encoding="utf-8")
    (root / "evil").symlink_to(outside_dir)
    files = path_utils.collect_documents(root, roots=[root.resolve()])
    assert [f.name for f in files] == ["real.md"]


def test_file_size_and_count_limits(tmp_path: Path) -> None:
    root = tmp_path / "docs"
    root.mkdir()
    big = root / "big.md"
    big.write_text("x" * 10, encoding="utf-8")
    with pytest.raises(path_utils.PathBoundaryError, match="大小上限"):
        path_utils.collect_documents(big, roots=[root.resolve()], max_file_bytes=5)

    for name in ("a.md", "b.md", "c.md"):
        (root / name).write_text("x", encoding="utf-8")
    with pytest.raises(path_utils.PathBoundaryError, match="文件数超过上限"):
        path_utils.collect_documents(root, roots=[root.resolve()], max_files=2)


def test_dsn_password_redacted() -> None:
    text = "mysql+pymysql://agentkernel:change-this-agent-password@127.0.0.1:3306/agentkernel"
    out = obs.redact(text)
    assert "change-this-agent-password" not in out
    assert ":***@" in out


def test_ingest_outside_root_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from agentkernel import __main__ as cli

    kb = KnowledgeBase(persist_dir=None)
    outside = tmp_path / "secret.md"
    outside.write_text("secret", encoding="utf-8")
    monkeypatch.setenv("AGENTKERNEL_DOC_ROOTS", str(tmp_path / "allowed"))
    (tmp_path / "allowed").mkdir()
    assert cli._ingest_path(kb, str(outside)) == 0
    kb.close()


def test_raw_mcp_requires_opt_in(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    from agentkernel import __main__ as cli

    monkeypatch.delenv("AGENTKERNEL_ALLOW_RAW_MCP", raising=False)
    monkeypatch.setenv("AGENTKERNEL_DOC_ROOTS", str(tmp_path))
    _, _, kb, clients = cli._build_agent(
        docs=None, kb_db=None, mcp_profiles=None, raw_mcp_commands=["echo hi"]
    )
    assert clients == []
    assert "拒绝 --mcp" in capsys.readouterr().out
    kb.close()
