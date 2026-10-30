"""G-24：LLM 出站 allowlist（防止 API key 被发往任意主机）。"""

from __future__ import annotations

import pytest

from agentkernel.adapters.llm import openai_compatible as llm
from agentkernel.utils import env


@pytest.fixture(autouse=True)
def _default_allowlist(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AGENTKERNEL_ALLOWED_LLM_HOSTS", raising=False)
    llm._client = None
    llm._client_env = None


def test_default_host_allowed() -> None:
    assert env.validate_base_url("https://api.deepseek.com") == "https://api.deepseek.com"
    assert env.validate_base_url("https://api.deepseek.com/") == "https://api.deepseek.com/"
    assert env.validate_base_url("https://API.DeepSeek.com:443/v1") == (
        "https://API.DeepSeek.com:443/v1"
    )


def test_unknown_host_rejected() -> None:
    with pytest.raises(env.LLMConfigError, match="不在允许列表"):
        env.validate_base_url("https://evil.example.com")


def test_plain_http_remote_rejected() -> None:
    with pytest.raises(env.LLMConfigError, match="必须使用 https"):
        env.validate_base_url("http://api.deepseek.com")


def test_loopback_http_allowed() -> None:
    assert env.validate_base_url("http://127.0.0.1:8000/v1") == "http://127.0.0.1:8000/v1"
    assert env.validate_base_url("http://localhost:8000") == "http://localhost:8000"


def test_env_override_replaces_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AGENTKERNEL_ALLOWED_LLM_HOSTS", "api.openai.com")
    assert env.validate_base_url("https://api.openai.com/v1") == "https://api.openai.com/v1"
    with pytest.raises(env.LLMConfigError, match="不在允许列表"):
        env.validate_base_url("https://api.deepseek.com")


def test_credentials_in_url_rejected() -> None:
    with pytest.raises(env.LLMConfigError, match="用户名/口令"):
        env.validate_base_url("https://user:pass@api.deepseek.com")


def test_invalid_url_rejected() -> None:
    with pytest.raises(env.LLMConfigError, match="不是合法 URL"):
        env.validate_base_url("api.deepseek.com")


def test_llm_client_refuses_disallowed_host(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test-not-real")
    monkeypatch.setenv("DEEPSEEK_BASE_URL", "http://evil.example.com")
    with pytest.raises(env.LLMConfigError, match="必须使用 https|不在允许列表"):
        llm._get_client()
