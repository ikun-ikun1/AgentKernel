"""内置工具：当前时间 + 安全计算器。"""
from __future__ import annotations

import ast
import operator
from collections.abc import Callable
from datetime import datetime
from typing import Any

from agentkernel.tools.registry import Registry, Tool


def _current_time(_: dict[str, Any]) -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


_ALLOWED_OPS: dict[type[ast.AST], Callable[..., Any]] = {
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
        left = _eval_node(node.left)
        right = _eval_node(node.right)
        if isinstance(node.op, ast.Pow) and (
            not isinstance(right, (int, float)) or abs(right) > 100
        ):
            raise ValueError("幂运算指数绝对值不能超过 100")
        result = _ALLOWED_OPS[type(node.op)](left, right)
        if isinstance(result, int) and result.bit_length() > 4096:
            raise ValueError("计算结果过大")
        return result
    if isinstance(node, ast.UnaryOp) and type(node.op) in _ALLOWED_OPS:
        return _ALLOWED_OPS[type(node.op)](_eval_node(node.operand))
    raise ValueError(f"不支持的表达式：{ast.dump(node)}")


def _safe_calc(expr: str) -> str:
    """白名单 AST 安全求值，禁止任意代码执行。"""
    if len(expr) > 200:
        raise ValueError("表达式过长")
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
            description="获取当前日期和时间；当用户询问「现在几点」「今天日期」时使用，返回 YYYY-MM-DD HH:MM:SS",
            parameters={"type": "object", "properties": {}},
            fn=_current_time,
        )
    )
    registry.register(
        Tool(
            name="calculator",
            description="安全计算数学表达式；当用户需要算术计算时使用，expression 只支持数字、四则运算、括号和 ** 幂运算，如 '123*456'",
            parameters={
                "type": "object",
                "properties": {
                    "expression": {
                        "type": "string",
                        "description": "数学表达式，如 '123*456' 或 '(1+2)*3'",
                    }
                },
                "required": ["expression"],
            },
            fn=_calculator,
        )
    )
