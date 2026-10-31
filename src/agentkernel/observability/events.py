"""事件组装（A3）：把 Agent 的运行事实转成 JSONL/OTLP 事件字典。

只做纯数据组装（字段顺序、条件字段、成本版本），不做 I/O；
发送仍由 Agent._emit 负责，观测失败不影响主流程。
"""

from __future__ import annotations

import time
from typing import Any

from agentkernel.utils import observability


def base_event(
    event: str,
    trace_id: str,
    turn_id: str,
    *,
    session_id: str | None,
    step: int,
    latency_ms: float,
    model: str | None,
    tokens: dict[str, int] | None,
    success: bool,
    error_type: str | None,
    span_id: str,
    parent_span_id: str | None,
    span_name: str,
    tool_name: str | None = None,
) -> dict[str, Any]:
    """12 个核心字段 + span 条件字段；tool_name 仅 tool/审计事件出现。"""
    payload: dict[str, Any] = {
        "event": event,
        "trace_id": trace_id,
        "session_id_hash": observability.hash_session(session_id),
        "turn_id": turn_id,
        "step": step,
        "latency_ms": latency_ms,
        "model": model,
        "tokens": tokens,
        "success": success,
        "error_type": error_type,
        "span": {"id": span_id, "parent_id": parent_span_id, "name": span_name},
    }
    if tool_name is not None:
        payload["tool_name"] = tool_name
    return payload


def turn_event(
    trace_id: str,
    turn_id: str,
    turn_span_id: str,
    stats: dict[str, Any],
    started: float,
    *,
    session_id: str | None,
    step: int,
    success: bool,
    error_type: str | None,
) -> dict[str, Any]:
    """组装 turn 事件：tokens/cost_usd/pricing_table_version 的条件字段与旧实现一致。"""
    usage = (
        observability.Usage(
            prompt_tokens=int(stats["prompt_tokens"]),
            completion_tokens=int(stats["completion_tokens"]),
        )
        if stats["usage_seen"]
        else None
    )
    tokens = {"in": usage.prompt_tokens, "out": usage.completion_tokens} if usage else None
    payload = base_event(
        "turn",
        trace_id,
        turn_id,
        session_id=session_id,
        step=step,
        latency_ms=round((time.perf_counter() - started) * 1000, 1),
        model=stats["model"],
        tokens=tokens,
        success=success,
        error_type=error_type,
        span_id=turn_span_id,
        parent_span_id=None,
        span_name="turn",
    )
    payload["cost_usd"] = observability.cost_usd(stats["model"], usage)
    if usage is not None:
        payload["pricing_table_version"] = observability.PRICING_TABLE_VERSION
    return payload


def budget_event(
    trace_id: str,
    turn_id: str,
    turn_span_id: str,
    reason: str,
    *,
    session_id: str | None,
    step: int,
) -> dict[str, Any]:
    """G-25：预算拦截单独成事件，便于告警与成本归因。"""
    return base_event(
        "budget_exceeded",
        trace_id,
        turn_id,
        session_id=session_id,
        step=step,
        latency_ms=0.0,
        model=None,
        tokens=None,
        success=False,
        error_type=reason,
        span_id=observability.new_span_id(),
        parent_span_id=turn_span_id,
        span_name="budget",
    )


def attach_tool_audit(payload: dict[str, Any], result: Any) -> dict[str, Any]:
    """把审批/幂等审计字段附加到 tool 事件（仅在相关时出现，旧事件形状不变）。"""
    if getattr(result, "approval_decision", None) is not None:
        payload["decision"] = result.approval_decision
        payload["approval_decision"] = result.approval_decision
        payload["reviewer"] = result.reviewer
        payload["idempotency_key"] = result.idempotency_key
        payload["argument_summary"] = result.argument_summary
        payload["approval_timestamp"] = result.approval_timestamp
    if getattr(result, "deduplicated", False):
        payload["deduplicated"] = True
    return payload
