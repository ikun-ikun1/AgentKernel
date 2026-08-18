"""统一错误类型（借鉴 workbench 的 runtime/exceptions.py 错误契约思想）。"""
from __future__ import annotations


class AgentKernelError(Exception):
    """项目基础异常。"""


class ToolNotFoundError(AgentKernelError):
    """工具未注册。"""


class ToolParamError(AgentKernelError):
    """工具参数校验失败。"""


class LLMError(AgentKernelError):
    """模型调用失败。"""
