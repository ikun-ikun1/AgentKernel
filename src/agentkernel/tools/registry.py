"""工具注册表：登记工具 → 生成描述 → 校验参数 → 执行 → 捕获异常。"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Callable

from agentkernel.utils.errors import ToolNotFoundError, ToolParamError


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict[str, Any]  # JSON Schema（含 required / properties）
    fn: Callable[[dict[str, Any]], str]


class Registry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool:
        if name not in self._tools:
            raise ToolNotFoundError(f"未注册的工具：{name}")
        return self._tools[name]

    def names(self) -> list[str]:
        return list(self._tools.keys())

    def describe(self) -> str:
        """生成给模型看的工具描述。"""
        lines = [f"- {t.name}: {t.description}" for t in self._tools.values()]
        return "\n".join(lines)

    def run(self, name: str, action_input: dict[str, Any]) -> str:
        """执行工具：校验参数 → 调用 → 异常转可读错误（不崩）。"""
        try:
            tool = self.get(name)
            self._validate(tool, action_input)
            return tool.fn(action_input)
        except ToolParamError as e:
            return f"[工具参数错误] {e}"
        except ToolNotFoundError as e:
            return f"[工具不存在] {e}"
        except Exception as e:  # 工具内部异常兜底
            return f"[工具错误] {type(e).__name__}: {e}"

    @staticmethod
    def _validate(tool: Tool, action_input: dict[str, Any]) -> None:
        """最小参数校验：required 字段必须存在。完整 JSON Schema 校验后续用 jsonschema 补。"""
        required = tool.parameters.get("required", [])
        for key in required:
            if key not in action_input:
                raise ToolParamError(f"缺少必填参数：{key}")
