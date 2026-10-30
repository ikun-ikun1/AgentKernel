"""DeepSeek 调用封装（OpenAI 兼容），统一 chat(messages) -> str。

教学点（对应 agent-study Ch11）：模型返回的只是「结构化文本」，真正执行函数的是
我们的代码。本模块只负责「取回文本」，解析与执行在 tools/ 与 runtime/agent.py。

工程细节：
- OpenAI client 复用（避免每轮对话都重建连接）；
- timeout + max_retries 防止 CLI 被一次网络抖动卡死；
- 失败统一抛 LLMError，调用方决定降级策略。
"""

from __future__ import annotations

from contextvars import ContextVar
from typing import Any

from agentkernel.utils import env
from agentkernel.utils.errors import LLMError
from agentkernel.utils.observability import Usage

_client: Any = None
_client_env: tuple[str, str, str] | None = None

# 最近一次调用的 usage/model，供 Agent 记账；chat 的返回签名保持不变（测试与 eval 会 monkeypatch chat）
_last_usage: ContextVar[Usage | None] = ContextVar("agentkernel_last_usage", default=None)
_last_model: ContextVar[str | None] = ContextVar("agentkernel_last_model", default=None)


def _get_client() -> Any:
    """按当前环境变量懒加载并复用 OpenAI client。"""
    global _client, _client_env
    try:
        from openai import OpenAI
    except ImportError as e:
        raise LLMError("未安装 openai SDK：pip install openai") from e

    key = env.get_api_key()
    # G-24：出站端点必须命中 allowlist，防止 key 被发往任意主机
    base_url = env.validate_base_url(env.get_base_url())
    model = env.get_model()
    signature = (key, base_url, model)
    if _client is None or _client_env != signature:
        _client = OpenAI(
            api_key=key,
            base_url=base_url,
            timeout=float(env.get_llm_timeout()),
            max_retries=int(env.get_llm_max_retries()),
        )
        _client_env = signature
    return _client


def chat(
    messages: list[dict[str, str]],
    *,
    temperature: float = 0.3,
    max_tokens: int | None = None,
) -> str:
    """调用 DeepSeek，返回模型文本输出。"""
    try:
        kwargs: dict[str, Any] = {
            "model": env.get_model(),
            "messages": messages,
            "temperature": temperature,
        }
        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens
        resp = _get_client().chat.completions.create(**kwargs)
        _last_model.set(str(kwargs["model"]))
        raw_usage = getattr(resp, "usage", None)
        if raw_usage is None:
            _last_usage.set(None)
        else:
            _last_usage.set(
                Usage(
                    prompt_tokens=int(getattr(raw_usage, "prompt_tokens", 0) or 0),
                    completion_tokens=int(getattr(raw_usage, "completion_tokens", 0) or 0),
                )
            )
        return resp.choices[0].message.content or ""
    except LLMError:
        raise
    except Exception as e:
        raise LLMError(f"模型调用失败：{e}") from e


def pop_usage() -> Usage | None:
    """取走并清空最近一次调用的 usage（mock 掉 chat 时返回 None）。"""
    usage = _last_usage.get()
    _last_usage.set(None)
    return usage


def last_model() -> str | None:
    return _last_model.get()


class OpenAICompatibleClient:
    """LLMClient 端口对象适配器；方法委托给本模块的函数实现。"""

    def chat(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.3,
        max_tokens: int | None = None,
    ) -> str:
        return chat(messages, temperature=temperature, max_tokens=max_tokens)

    def pop_usage(self) -> Usage | None:
        return pop_usage()

    def last_model(self) -> str | None:
        return last_model()
