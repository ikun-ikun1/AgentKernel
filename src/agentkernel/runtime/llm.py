"""DeepSeek 调用封装（OpenAI 兼容），统一 chat(messages) -> str。

教学点（对应 agent-study Ch11）：模型返回的只是「结构化文本」，真正执行函数的是
我们的代码。本模块只负责「取回文本」，解析与执行在 tools/ 与 runtime/agent.py。

工程细节：
- OpenAI client 复用（避免每轮对话都重建连接）；
- timeout + max_retries 防止 CLI 被一次网络抖动卡死；
- 失败统一抛 LLMError，调用方决定降级策略。
"""
from __future__ import annotations

from typing import Any

from agentkernel.utils import env
from agentkernel.utils.errors import LLMError

_client: Any = None
_client_env: tuple[str, str, str] | None = None


def _get_client() -> Any:
    """按当前环境变量懒加载并复用 OpenAI client。"""
    global _client, _client_env
    try:
        from openai import OpenAI
    except ImportError as e:
        raise LLMError("未安装 openai SDK：pip install openai") from e

    key = env.get_api_key()
    base_url = env.get_base_url()
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
        return resp.choices[0].message.content or ""
    except LLMError:
        raise
    except Exception as e:
        raise LLMError(f"模型调用失败：{e}") from e
