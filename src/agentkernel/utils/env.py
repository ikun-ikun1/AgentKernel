"""环境变量读取（.env），API Key 不硬编码。"""

from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import urlparse

# 项目根目录：src/agentkernel/utils/env.py → parents[3] = AgentKernel/
_PROJECT_ROOT = Path(__file__).resolve().parents[3]


def load_env() -> None:
    """加载项目根目录的 .env（幂等，可重复调用）。"""
    try:
        from dotenv import load_dotenv

        load_dotenv(_PROJECT_ROOT / ".env")
    except ImportError:
        # 未装 python-dotenv 时，依赖用户自行 export 环境变量
        pass


def get_api_key() -> str:
    """读取 DeepSeek API Key，缺失则抛明确错误。"""
    load_env()
    key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    if not key:
        raise RuntimeError(
            "缺少 DEEPSEEK_API_KEY：请在项目根目录 .env 里加一行 DEEPSEEK_API_KEY=sk-xxx"
        )
    return key


DEFAULT_LLM_HOSTS = ("api.deepseek.com",)
LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}


class LLMConfigError(RuntimeError):
    """LLM 端点配置不安全（不在 allowlist / 非 https / 带凭据）。"""


def allowed_llm_hosts() -> tuple[str, ...]:
    raw = os.environ.get("AGENTKERNEL_ALLOWED_LLM_HOSTS", "")
    hosts = tuple(host.strip().lower() for host in raw.split(",") if host.strip())
    return hosts or DEFAULT_LLM_HOSTS


def get_base_url() -> str:
    return os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")


def validate_base_url(url: str | None = None) -> str:
    """出站 allowlist（G-24）：只允许 https + 白名单主机（本机回环可用 http）。

    目的：防止改一个环境变量就把 API key 发往任意主机。
    """
    candidate = (url if url is not None else get_base_url()).strip()
    parsed = urlparse(candidate)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise LLMConfigError(f"DEEPSEEK_BASE_URL 不是合法 URL：{candidate!r}")
    if parsed.username or parsed.password:
        raise LLMConfigError("DEEPSEEK_BASE_URL 不允许携带用户名/口令")
    host = parsed.hostname.lower()
    if host in LOOPBACK_HOSTS:
        # 本机回环允许 http（本地 mock/ollama 等），不出网
        return candidate
    if parsed.scheme == "http" and host not in LOOPBACK_HOSTS:
        raise LLMConfigError(f"DEEPSEEK_BASE_URL 必须使用 https（本机回环地址除外）：{candidate!r}")
    allowed = allowed_llm_hosts()
    if host not in allowed:
        raise LLMConfigError(
            f"DEEPSEEK_BASE_URL 的主机不在允许列表：{host}"
            f"（可用 AGENTKERNEL_ALLOWED_LLM_HOSTS 配置，默认 {', '.join(DEFAULT_LLM_HOSTS)}）"
        )
    return candidate


def get_model() -> str:
    return os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")


def get_llm_timeout() -> str:
    """OpenAI client 超时秒数（默认 60）。"""
    return os.environ.get("AGENTKERNEL_LLM_TIMEOUT", "60")


def get_llm_max_retries() -> str:
    """OpenAI client 最大重试次数（默认 2）。"""
    return os.environ.get("AGENTKERNEL_LLM_MAX_RETRIES", "2")
