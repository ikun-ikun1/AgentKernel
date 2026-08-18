"""内置工具：当前时间 + 安全计算器。"""
from __future__ import annotations
import ast
import operator
from datetime import datetime
from typing import Any

from agentkernel.tools.registry import Registry, Tool


def _current_time(_: dict[str, Any]) -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


_ALLOWED_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Pow: operator.pow,
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
}


def _eval_node(node: ast.AST) -> float:
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _ALLOWED_OPS:
        return _ALLOWED_OPS[type(node.op)](_eval_node(node.left), _eval_node(node.right))
    if isinstance(node, ast.UnaryOp) and type(node.op) in _ALLOWED_OPS:
        return _ALLOWED_OPS[type(node.op)](_eval_node(node.operand))
    raise ValueError(f"不支持的表达式：{ast.dump(node)}")


def _safe_calc(expr: str) -> str:
    """白名单 AST 安全求值，禁止任意代码执行。"""
    tree = ast.parse(expr, mode="eval")
    result = _eval_node(tree.body)
    return str(int(result) if float(result).is_integer() else result)


def _calculator(args: dict[str, Any]) -> str:
    expr = str(args.get("expression", "")).strip()
    if not expr:
        raise ValueError("缺少 expression 参数")
    return _safe_calc(expr)


def register_builtin(registry: Registry) -> None:
    registry.register(
        Tool(
            name="get_current_time",
            description="返回当前时间，无参数",
            parameters={"type": "object", "properties": {}},
            fn=_current_time,
        )
    )
    registry.register(
        Tool(
            name="calculator",
            description="计算四则运算表达式，参数 expression 如 '123*456'",
            parameters={
                "type": "object",
                "properties": {"expression": {"type": "string"}},
                "required": ["expression"],
            },
            fn=_calculator,
        )
    )
