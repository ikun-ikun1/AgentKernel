"""LLM 适配层：fake OpenAI client 覆盖 client 复用/重建、usage 捕获与异常包装。"""

from __future__ import annotations

import sys
import types
from typing import ClassVar

import pytest

from agentkernel.runtime import llm
from agentkernel.utils.errors import LLMError
from agentkernel.utils.observability import Usage


class _Usage:
    prompt_tokens = 11
    completion_tokens = 7


class _Message:
    content = "hello"


class _Choice:
    message = _Message()


class _Response:
    def __init__(self) -> None:
        self.choices = [_Choice()]
        self.usage = _Usage()


class _Completions:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return _Response()


class _Chat:
    def __init__(self) -> None:
        self.completions = _Completions()


class FakeOpenAI:
    instances: ClassVar[list[FakeOpenAI]] = []

    def __init__(self, **kwargs) -> None:
        self.kwargs = kwargs
        self.chat = _Chat()
        FakeOpenAI.instances.append(self)


@pytest.fixture(autouse=True)
def fake_openai(monkeypatch: pytest.MonkeyPatch):
    module = types.ModuleType("openai")
    module.OpenAI = FakeOpenAI  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "openai", module)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test-not-real")
    monkeypatch.setenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
    monkeypatch.setenv("DEEPSEEK_MODEL", "deepseek-chat")
    monkeypatch.delenv("AGENTKERNEL_ALLOWED_LLM_HOSTS", raising=False)
    llm._client = None
    llm._client_env = None
    FakeOpenAI.instances.clear()
    yield
    llm._client = None
    llm._client_env = None


def test_client_reused_and_rebuilt_on_model_change(monkeypatch: pytest.MonkeyPatch) -> None:
    first = llm._get_client()
    second = llm._get_client()
    assert first is second
    assert len(FakeOpenAI.instances) == 1
    assert first.kwargs["api_key"] == "sk-test-not-real"
    assert first.kwargs["base_url"] == "https://api.deepseek.com"
    assert first.kwargs["timeout"] == 60.0
    assert first.kwargs["max_retries"] == 2

    monkeypatch.setenv("DEEPSEEK_MODEL", "deepseek-reasoner")
    third = llm._get_client()
    assert third is not first
    assert len(FakeOpenAI.instances) == 2


def test_chat_captures_usage_and_model() -> None:
    assert llm.chat([{"role": "user", "content": "hi"}]) == "hello"
    assert llm.pop_usage() == Usage(prompt_tokens=11, completion_tokens=7)
    assert llm.pop_usage() is None
    assert llm.last_model() == "deepseek-chat"


def test_chat_passes_max_tokens() -> None:
    llm.chat([{"role": "user", "content": "hi"}], max_tokens=128)
    client = llm._get_client()
    assert client.chat.completions.calls[-1]["max_tokens"] == 128


def test_chat_wraps_provider_error(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Boom:
        class chat:
            class completions:
                @staticmethod
                def create(**kwargs):
                    raise RuntimeError("network down")

    monkeypatch.setattr(llm, "_get_client", lambda: _Boom())
    with pytest.raises(LLMError, match="模型调用失败"):
        llm.chat([{"role": "user", "content": "hi"}])


def test_missing_openai_sdk_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "openai", None)
    with pytest.raises(LLMError, match="未安装 openai SDK"):
        llm._get_client()
