"""环境变量读取（.env），API Key 不硬编码。"""
from __future__ import annotations

import os
from pathlib import Path

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


def get_base_url() -> str:
    return os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")


def get_model() -> str:
    return os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")


def get_llm_timeout() -> str:
    """OpenAI client 超时秒数（默认 60）。"""
    return os.environ.get("AGENTKERNEL_LLM_TIMEOUT", "60")


def get_llm_max_retries() -> str:
    """OpenAI client 最大重试次数（默认 2）。"""
    return os.environ.get("AGENTKERNEL_LLM_MAX_RETRIES", "2")
