"""MCP server profile（P0-5）：命名 + 精确 argv + env 白名单。

设计：
- CLI 只能选择 `--mcp-profile <name>`，命令与参数全部来自 profile 文件，**不接受任意命令字符串**。
- `command` 必须是规范化绝对路径（realpath）；解释器（sh/python/node…）需显式 `allow_interpreter`。
- 子进程 env 只注入白名单键，并强制剔除 `DEEPSEEK_*`/`AGENTKERNEL_*`/`OPENAI_*`/`AWS_*` 等。
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path

BASE_ENV_ALLOWLIST = ("PATH", "HOME", "LANG", "LC_ALL", "PYTHONPATH", "TMPDIR")
INTERPRETERS = {"sh", "bash", "zsh", "dash", "python", "python3", "node", "perl", "ruby"}
SECRET_ENV_PREFIXES = ("DEEPSEEK_", "AGENTKERNEL_", "OPENAI_", "AWS_", "ANTHROPIC_")


class McpProfileError(ValueError):
    """profile 配置非法或未声明。"""


@dataclass(frozen=True)
class McpProfile:
    name: str
    command: str
    args: tuple[str, ...] = ()
    env_allowlist: tuple[str, ...] = ()
    allow_interpreter: bool = False


def default_profiles_path() -> Path:
    raw = os.environ.get("AGENTKERNEL_MCP_PROFILES") or "~/.agentkernel/mcp_profiles.toml"
    return Path(raw).expanduser()


def validate_profile(profile: McpProfile) -> None:
    command = Path(profile.command)
    if not command.is_absolute():
        raise McpProfileError(f"profile {profile.name}: command 必须是绝对路径")
    try:
        resolved = command.resolve(strict=True)
    except OSError:
        raise McpProfileError(f"profile {profile.name}: command 不存在：{command}") from None
    if resolved != command:
        raise McpProfileError(
            f"profile {profile.name}: command 必须是 realpath（{resolved}），当前为 {command}"
        )
    if not os.access(resolved, os.X_OK):
        raise McpProfileError(f"profile {profile.name}: command 不可执行：{resolved}")
    if command.name in INTERPRETERS and not profile.allow_interpreter:
        raise McpProfileError(
            f"profile {profile.name}: 解释器 {command.name} 需显式 allow_interpreter = true"
        )
    if not profile.allow_interpreter and "-c" in profile.args:
        raise McpProfileError(
            f"profile {profile.name}: 出现 -c 参数，需显式 allow_interpreter = true"
        )


def load_profiles(path: Path | None = None) -> dict[str, McpProfile]:
    cfg = Path(path).expanduser() if path else default_profiles_path()
    if not cfg.exists():
        return {}
    try:
        data = tomllib.loads(cfg.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise McpProfileError(f"profile 文件解析失败：{cfg}：{exc}") from exc

    profiles: dict[str, McpProfile] = {}
    for item in data.get("mcp_profiles", []):
        try:
            profile = McpProfile(
                name=str(item["name"]),
                command=str(item["command"]),
                args=tuple(str(arg) for arg in item.get("args", [])),
                env_allowlist=tuple(str(key) for key in item.get("env_allowlist", [])),
                allow_interpreter=bool(item.get("allow_interpreter", False)),
            )
        except KeyError as exc:
            raise McpProfileError(f"profile 缺少字段 {exc}：{item}") from exc
        validate_profile(profile)
        if profile.name in profiles:
            raise McpProfileError(f"profile 重名：{profile.name}")
        profiles[profile.name] = profile
    return profiles


def select_profile(name: str, profiles: dict[str, McpProfile] | None = None) -> McpProfile:
    table = profiles if profiles is not None else load_profiles()
    if name not in table:
        known = ", ".join(sorted(table)) or "（无）"
        raise McpProfileError(f"未声明的 MCP profile：{name}（可用：{known}）")
    return table[name]


def build_child_env(profile: McpProfile, source: dict[str, str] | None = None) -> dict[str, str]:
    base = dict(os.environ if source is None else source)
    allow = set(profile.env_allowlist or BASE_ENV_ALLOWLIST)
    env: dict[str, str] = {}
    for key, value in base.items():
        if key.startswith(SECRET_ENV_PREFIXES):
            continue
        if key in allow:
            env[key] = value
    env.setdefault("PATH", "/usr/local/bin:/usr/bin:/bin")
    return env
