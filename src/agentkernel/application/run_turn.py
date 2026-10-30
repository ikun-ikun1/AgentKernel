"""一轮 ReAct 编排（A7.2）：从 Agent 抽出循环，Agent 只做 facade。

TurnHost 是协议（不是具体 Agent），application 层不依赖 runtime/agent.py。
"""

from __future__ import annotations

import time
from typing import Any, Protocol

from agentkernel.observability import events
from agentkernel.ports.llm import LLMClient
from agentkernel.tools import contracts
from agentkernel.tools.registry import Registry
from agentkernel.utils import observability


class TurnHost(Protocol):
    registry: Registry
    llm_client: LLMClient
    max_steps: int
    max_tool_calls_per_turn: int
    session_token_budget: int
    session_tokens: int
    session_id: str | None
    _step: int

    def _build_messages(self, history: list[dict[str, str]]) -> list[dict[str, str]]: ...

    def _parse(self, raw: str) -> contracts.Action | None: ...

    def _execute_tool_call(
        self,
        call: contracts.ToolCall,
        history: list[dict[str, str]],
        trace_id: str,
        turn_id: str,
        turn_span_id: str,
    ) -> None: ...

    def _emit(self, payload: dict[str, object]) -> None: ...


def _emit_turn(
    host: TurnHost,
    trace_id: str,
    turn_id: str,
    turn_span_id: str,
    stats: dict[str, object],
    started: float,
    *,
    success: bool,
    error_type: str | None,
) -> None:
    host._emit(
        events.turn_event(
            trace_id,
            turn_id,
            turn_span_id,
            stats,
            started,
            session_id=host.session_id,
            step=host._step,
            success=success,
            error_type=error_type,
        )
    )


def _emit_budget(
    host: TurnHost, trace_id: str, turn_id: str, turn_span_id: str, reason: str
) -> None:
    host._emit(
        events.budget_event(
            trace_id,
            turn_id,
            turn_span_id,
            reason,
            session_id=host.session_id,
            step=host._step,
        )
    )


def run_turn(host: TurnHost, user_input: str, history: list[dict[str, str]]) -> str:
    """跑一轮对话，就地更新 history。返回最终回答。"""
    trace_id = observability.new_trace_id()
    turn_id = observability.new_turn_id()
    turn_span_id = observability.new_span_id()
    started = time.perf_counter()
    stats: dict[str, Any] = {
        "steps": 0,
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "usage_seen": False,
        "model": None,
    }
    history.append({"role": "user", "content": user_input})
    tool_calls_this_turn = 0

    try:
        for step in range(1, host.max_steps + 1):
            host._step = step
            stats["steps"] = step
            if host.session_token_budget and host.session_tokens >= host.session_token_budget:
                _emit_turn(
                    host,
                    trace_id,
                    turn_id,
                    turn_span_id,
                    stats,
                    started,
                    success=False,
                    error_type="TokenBudget",
                )
                _emit_budget(host, trace_id, turn_id, turn_span_id, "TokenBudget")
                return "（已达到会话 token 预算上限，本轮停止；可 /new 开新会话）"
            host.llm_client.pop_usage()
            raw = host.llm_client.chat(host._build_messages(history))
            usage = host.llm_client.pop_usage()
            if usage is not None:
                stats["usage_seen"] = True
                stats["prompt_tokens"] = int(stats["prompt_tokens"]) + usage.prompt_tokens
                stats["completion_tokens"] = (
                    int(stats["completion_tokens"]) + usage.completion_tokens
                )
                host.session_tokens += usage.prompt_tokens + usage.completion_tokens
            model = host.llm_client.last_model()
            if model:
                stats["model"] = model
            action = host._parse(raw)

            if isinstance(action, contracts.FinalAnswer):
                history.append({"role": "assistant", "content": action.text})
                _emit_turn(
                    host,
                    trace_id,
                    turn_id,
                    turn_span_id,
                    stats,
                    started,
                    success=True,
                    error_type=None,
                )
                return action.text

            if (
                isinstance(action, (contracts.ToolCall, contracts.ToolCalls))
                and tool_calls_this_turn >= host.max_tool_calls_per_turn
            ):
                _emit_turn(
                    host,
                    trace_id,
                    turn_id,
                    turn_span_id,
                    stats,
                    started,
                    success=False,
                    error_type="ToolCallBudget",
                )
                _emit_budget(host, trace_id, turn_id, turn_span_id, "ToolCallBudget")
                return "（单轮工具调用超过上限，本轮停止）"

            if isinstance(action, contracts.ToolCall):
                tool_calls_this_turn += 1
                history.append({"role": "assistant", "content": raw})
                host._execute_tool_call(action, history, trace_id, turn_id, turn_span_id)
                continue

            if isinstance(action, contracts.ToolCalls):
                tool_calls_this_turn += len(action.calls)
                history.append({"role": "assistant", "content": raw})
                for call in action.calls:
                    host._execute_tool_call(call, history, trace_id, turn_id, turn_span_id)
                continue

            history.append({"role": "assistant", "content": raw})
            _emit_turn(
                host,
                trace_id,
                turn_id,
                turn_span_id,
                stats,
                started,
                success=True,
                error_type="parse_fallback",
            )
            return raw
    except Exception as exc:
        _emit_turn(
            host,
            trace_id,
            turn_id,
            turn_span_id,
            stats,
            started,
            success=False,
            error_type=type(exc).__name__,
        )
        raise

    _emit_turn(
        host, trace_id, turn_id, turn_span_id, stats, started, success=False, error_type="MaxSteps"
    )
    return "（达到最大步数上限，未完成）"
