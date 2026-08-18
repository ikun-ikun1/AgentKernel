"""DeepSeek 调用封装（OpenAI 兼容），统一 chat(messages) -> str。"""
from __future__ import annotations

from agentkernel.utils import env
from agentkernel.utils.errors import LLMError


def chat(messages: list[dict[str, str]]) -> str:
    """调用 DeepSeek，返回模型文本输出。"""
    try:
        from openai import OpenAI
    except ImportError as e:
        raise LLMError("未安装 openai SDK：pip install openai") from e

    client = OpenAI(api_key=env.get_api_key(), base_url=env.get_base_url())
    try:
        resp = client.chat.completions.create(model=env.get_model(), messages=messages)
        return resp.choices[0].message.content or ""
    except Exception as e:
        raise LLMError(f"模型调用失败：{e}") from e
