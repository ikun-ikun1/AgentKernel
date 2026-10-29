"""工具注册表：登记工具 → 生成描述 → 校验参数 → 执行 → 捕获异常。

个人项目特点：不引入 jsonschema 依赖，手写一个最小 JSON Schema 校验器
（type / properties / required / enum / items / additionalProperties），
既能讲清「工具参数为什么可靠」，也符合项目「零框架、少依赖」的定位。
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from time import perf_counter
from typing import Any

from agentkernel.utils.errors import ToolNotFoundError, ToolParamError


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict[str, Any]  # JSON Schema（含 required / properties）
    fn: Callable[[dict[str, Any]], str]


class ToolExecutionResult(str):
    """兼容字符串调用方，同时携带工具执行状态元数据。"""

    success: bool
    error_type: str | None
    duration_ms: float

    def __new__(
        cls,
        output: str,
        *,
        success: bool,
        error_type: str | None = None,
        duration_ms: float = 0.0,
    ) -> ToolExecutionResult:
        instance = super().__new__(cls, output)
        instance.success = success
        instance.error_type = error_type
        instance.duration_ms = duration_ms
        return instance


def validate_parameters(schema: dict[str, Any], value: Any, path: str = "参数") -> None:
    """最小 JSON Schema 校验器：只实现 Agent 工具需要的子集，报错带路径。"""
    if "enum" in schema and value not in schema["enum"]:
        raise ToolParamError(f"{path} 必须是 {schema['enum']!r} 之一")

    expected = schema.get("type")
    if expected is None:
        return

    if expected == "object":
        if not isinstance(value, dict):
            raise ToolParamError(f"{path} 必须是对象")
        for key in schema.get("required", []):
            if key not in value:
                raise ToolParamError(f"缺少必填参数：{key}")
        if schema.get("additionalProperties") is False:
            allowed = set(schema.get("properties", {}).keys())
            extra = set(value.keys()) - allowed
            if extra:
                raise ToolParamError(f"{path} 含未允许字段：{sorted(extra)}")
        for key, sub_schema in schema.get("properties", {}).items():
            if key in value:
                validate_parameters(sub_schema, value[key], f"{path}.{key}")
        return

    if expected == "string":
        if not isinstance(value, str):
            raise ToolParamError(f"{path} 必须是字符串")
        return
    if expected == "integer":
        if not isinstance(value, int) or isinstance(value, bool):
            raise ToolParamError(f"{path} 必须是整数")
        return
    if expected == "number":
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            raise ToolParamError(f"{path} 必须是数字")
        return
    if expected == "boolean":
        if not isinstance(value, bool):
            raise ToolParamError(f"{path} 必须是布尔值")
        return
    if expected == "array":
        if not isinstance(value, list):
            raise ToolParamError(f"{path} 必须是数组")
        for i, item in enumerate(value):
            validate_parameters(schema.get("items", {}), item, f"{path}[{i}]")
        return
    if expected == "null":
        if value is not None:
            raise ToolParamError(f"{path} 必须是 null")
        return


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
        """生成给模型看的工具描述（含参数 schema 摘要）。"""
        lines = []
        for t in self._tools.values():
            params = self._describe_parameters(t.parameters)
            suffix = f"；参数：{params}" if params else "；无参数"
            lines.append(f"- {t.name}: {t.description}{suffix}")
        return "\n".join(lines)

    def run(self, name: str, action_input: dict[str, Any]) -> ToolExecutionResult:
        """执行工具：校验参数 → 调用 → 异常转可读错误（不崩）。"""
        started = perf_counter()
        try:
            tool = self.get(name)
            self._validate(tool, action_input)
            return ToolExecutionResult(
                str(tool.fn(action_input)),
                success=True,
                duration_ms=(perf_counter() - started) * 1000,
            )
        except ToolParamError as e:
            return self._error_result("工具参数错误", e, started)
        except ToolNotFoundError as e:
            return self._error_result("工具不存在", e, started)
        except Exception as e:  # 工具内部异常兜底
            return self._error_result("工具错误", e, started, type(e).__name__)

    @staticmethod
    def _error_result(
        prefix: str,
        error: Exception,
        started: float,
        error_type: str | None = None,
    ) -> ToolExecutionResult:
        return ToolExecutionResult(
            f"[{prefix}] {error}" if error_type is None else f"[{prefix}] {error_type}: {error}",
            success=False,
            error_type=error_type or type(error).__name__,
            duration_ms=(perf_counter() - started) * 1000,
        )

    @staticmethod
    def _validate(tool: Tool, action_input: dict[str, Any]) -> None:
        """JSON Schema 校验；错误信息直接回灌给模型，让它重试。"""
        validate_parameters(tool.parameters, action_input)

    @staticmethod
    def _describe_parameters(parameters: dict[str, Any]) -> str:
        props = parameters.get("properties", {})
        required = set(parameters.get("required", []))
        if not props:
            return ""
        parts = []
        for key, schema in props.items():
            mark = "必填" if key in required else "可选"
            desc = schema.get("description", "")
            extra = schema.get("type", "any")
            if "enum" in schema:
                extra += f"，取值 {schema['enum']!r}"
            if "default" in schema:
                extra += f"，默认 {schema['default']!r}"
            text = f"{key} ({extra}, {mark}"
            if desc:
                text += f"：{desc}"
            text += ")"
            parts.append(text)
        return "; ".join(parts)
