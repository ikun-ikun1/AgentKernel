"""ReAct 主循环：思考 → 行动 → 观察 → 回复，带上下文管理。

上下文管理策略（个人项目特点：无框架、无 tokenizer，按字符预算工程化实现）：
- truncate：超预算时保留「首条用户要求 + 最近消息」，防止第 10 轮把第 1 轮要求丢了。
- compact：优先调模型做摘要压缩，把旧历史压成一条「对话摘要」；模型不可用时降级为 truncate。
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from agentkernel.runtime import llm
from agentkernel.tools import contracts, json_repair
from agentkernel.tools.registry import Registry
from agentkernel.utils import observability

SYSTEM_PROMPT = """你是一个能调用工具的 Agent。

回答规则（严格遵守，只输出 JSON，不要输出其他内容）：
- 如果需要用一个工具，输出：
  {"action": "工具名", "action_input": {"参数": "值"}}
- 如果需要同时用多个互相独立的工具，输出：
  {"actions": [{"action": "工具名1", "action_input": {...}}, {"action": "工具名2", "action_input": {...}}]}
- 如果已经能回答用户，输出：
  {"action": "final_answer", "action_input": "你的回答内容"}
- 如果使用了 knowledge_query 工具，最终回答必须带上工具结果里的「来源：文档名」。

可用工具：
{tools}
"""

COMPACT_PROMPT = """请把下面的对话历史压缩成一段 200 字以内的中文摘要，保留：
1. 用户最初的要求和约束；
2. 已经完成的工具调用与关键结果；
3. 尚未完成的事项。

对话历史：
{history}

只输出摘要本身，不要输出其他内容。"""


@dataclass
class ContextConfig:
    """上下文管理配置（字符预算，避免引入 tokenizer 依赖）。"""

    max_history_chars: int = 8000  # 送入模型的历史消息字符上限
    compact_trigger_chars: int = 6000  # 超过该值触发 compact 压缩
    keep_recent_chars: int = 2000  # compact 时保留的最近消息字符数


# 工具调用观察者：在每次工具执行后回调，用于审计日志等（对应 agent-study Ch14 tool_logs）
ToolObserver = Callable[[str, dict[str, Any], str], None]
# 结构化事件观察者：每轮 1 条 turn、每次工具 1 条 tool（字段表见 utils/observability.py）
EventObserver = Callable[[dict[str, Any]], None]


class Agent:
    def __init__(
        self,
        registry: Registry,
        max_steps: int = 10,
        context: ContextConfig | None = None,
        on_tool_call: ToolObserver | None = None,
        on_event: EventObserver | None = None,
        session_id: str | None = None,
    ) -> None:
        self.registry = registry
        self.max_steps = max_steps
        self.context = context or ContextConfig()
        self.on_tool_call = on_tool_call
        self.on_event = on_event
        self.session_id = session_id
        self.audit_failures = 0
        self._step = 0

    def run(self, user_input: str, history: list[dict[str, str]]) -> str:
        """跑一轮对话，就地更新 history。返回最终回答。

        观测：每轮发 1 条 `turn` 事件（含 trace/turn id、步数、token、成本），
        工具事件由 `_execute_tool_call` 发出；观测失败不影响主流程。
        """
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

        try:
            for step in range(1, self.max_steps + 1):
                self._step = step
                stats["steps"] = step
                llm.pop_usage()
                raw = llm.chat(self._build_messages(history))
                usage = llm.pop_usage()
                if usage is not None:
                    stats["usage_seen"] = True
                    stats["prompt_tokens"] += usage.prompt_tokens
                    stats["completion_tokens"] += usage.completion_tokens
                model = llm.last_model()
                if model:
                    stats["model"] = model
                action = self._parse(raw)

                if isinstance(action, contracts.FinalAnswer):
                    history.append({"role": "assistant", "content": action.text})
                    self._emit_turn(
                        trace_id,
                        turn_id,
                        turn_span_id,
                        stats,
                        started,
                        success=True,
                        error_type=None,
                    )
                    return action.text

                if isinstance(action, contracts.ToolCall):
                    history.append({"role": "assistant", "content": raw})
                    self._execute_tool_call(action, history, trace_id, turn_id, turn_span_id)
                    continue  # 回到循环，让模型基于观察结果继续

                if isinstance(action, contracts.ToolCalls):
                    # 多工具调用：当前按顺序执行（模型应按无依赖关系来给多个调用）。
                    # 若要做真并行，可在无依赖时用线程池；教学版保持串行以便解释观察回灌顺序。
                    history.append({"role": "assistant", "content": raw})
                    for call in action.calls:
                        self._execute_tool_call(call, history, trace_id, turn_id, turn_span_id)
                    continue

                # 解析失败 → 降级为纯文本回答（OpenClaw：不能晋升为工具调用就当普通文本）
                history.append({"role": "assistant", "content": raw})
                self._emit_turn(
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
            self._emit_turn(
                trace_id,
                turn_id,
                turn_span_id,
                stats,
                started,
                success=False,
                error_type=type(exc).__name__,
            )
            raise

        self._emit_turn(
            trace_id, turn_id, turn_span_id, stats, started, success=False, error_type="MaxSteps"
        )
        return "（达到最大步数上限，未完成）"

    def _execute_tool_call(
        self,
        call: contracts.ToolCall,
        history: list[dict[str, str]],
        trace_id: str,
        turn_id: str,
        turn_span_id: str,
    ) -> None:
        """执行单个工具调用，观察结果回灌历史，并触发审计观察者与 tool 事件。"""
        started = time.perf_counter()
        result = self.registry.run(call.action, call.action_input)
        latency_ms = round((time.perf_counter() - started) * 1000, 1)
        if self.on_tool_call is not None:
            try:
                self.on_tool_call(call.action, call.action_input, result)
            except Exception:
                # 审计失败不影响主流程，但必须可见（禁止静默 pass）
                self.audit_failures += 1
                self._emit(
                    self._base_event(
                        "audit_failed",
                        trace_id,
                        turn_id,
                        latency_ms=0.0,
                        model=None,
                        tokens=None,
                        success=False,
                        error_type="AuditError",
                        span_id=observability.new_span_id(),
                        parent_span_id=turn_span_id,
                        span_name="audit.log",
                    )
                )
        self._emit(
            self._base_event(
                "tool",
                trace_id,
                turn_id,
                latency_ms=latency_ms,
                model=None,
                tokens=None,
                success=bool(getattr(result, "success", True)),
                error_type=getattr(result, "error_type", None),
                tool_name=call.action,
                span_id=observability.new_span_id(),
                parent_span_id=turn_span_id,
                span_name=f"tool.{call.action}",
            )
        )
        history.append({"role": "user", "content": f"工具 {call.action} 返回：{result}"})

    # ---- 观测 ----

    def _base_event(
        self,
        event: str,
        trace_id: str,
        turn_id: str,
        *,
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
        payload: dict[str, Any] = {
            "event": event,
            "trace_id": trace_id,
            "session_id_hash": observability.hash_session(self.session_id),
            "turn_id": turn_id,
            "step": self._step,
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

    def _emit_turn(
        self,
        trace_id: str,
        turn_id: str,
        turn_span_id: str,
        stats: dict[str, Any],
        started: float,
        *,
        success: bool,
        error_type: str | None,
    ) -> None:
        usage = (
            observability.Usage(
                prompt_tokens=int(stats["prompt_tokens"]),
                completion_tokens=int(stats["completion_tokens"]),
            )
            if stats["usage_seen"]
            else None
        )
        tokens = {"in": usage.prompt_tokens, "out": usage.completion_tokens} if usage else None
        payload = self._base_event(
            "turn",
            trace_id,
            turn_id,
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
        self._emit(payload)

    def _emit(self, payload: dict[str, Any]) -> None:
        if self.on_event is None:
            return
        try:
            self.on_event(payload)
        except Exception:  # 观测失败不得影响主流程
            self.audit_failures += 1

    def _build_messages(self, history: list[dict[str, str]]) -> list[dict[str, str]]:
        # 注意：SYSTEM_PROMPT 含 JSON 示例的 {} 括号，不能用 str.format，
        # 用 replace 只替换 {tools} 占位符，避免把 JSON 示例误当格式化字段。
        system = SYSTEM_PROMPT.replace("{tools}", self.registry.describe())
        return [{"role": "system", "content": system}] + self._prepare_history(history)

    # ---- 上下文管理 ----

    @staticmethod
    def _chars(messages: list[dict[str, str]]) -> int:
        return sum(len(m["content"]) for m in messages)

    def _prepare_history(self, history: list[dict[str, str]]) -> list[dict[str, str]]:
        """返回送入模型的历史消息；超预算时压缩/截断。"""
        if self._chars(history) <= self.context.max_history_chars:
            return history

        if self._chars(history) > self.context.compact_trigger_chars:
            compacted = self._try_compact(history)
            if compacted is not None and self._chars(compacted) <= self.context.max_history_chars:
                return compacted

        return self._truncate(history)

    def _truncate(self, history: list[dict[str, str]]) -> list[dict[str, str]]:
        """truncate：固定首条用户消息（原始要求），其余从后往前保留最近消息。"""
        if not history:
            return []
        first_user = history[0] if history[0]["role"] == "user" else None
        budget = self.context.max_history_chars - (len(first_user["content"]) if first_user else 0)
        recent: list[dict[str, str]] = []
        used = 0
        for msg in reversed(history[1:] if first_user else history):
            need = len(msg["content"])
            if used + need > budget:
                break
            recent.append(msg)
            used += need
        recent.reverse()

        if first_user is None:
            return recent
        # 首条消息和最近消息可能重叠（当只有一条消息时），避免重复
        if recent and recent[0] is first_user:
            return recent
        return [first_user] + recent

    def _try_compact(self, history: list[dict[str, str]]) -> list[dict[str, str]] | None:
        """compact：调模型把旧历史压成摘要，失败返回 None 由调用方降级 truncate。"""
        if len(history) < 2:
            return None
        recent = self._truncate_recent(history, self.context.keep_recent_chars)
        older = history[: len(history) - len(recent)]
        if not older:
            return recent
        try:
            compact_prompt = COMPACT_PROMPT.replace("{history}", self._format_for_compact(older))
            summary = llm.chat([{"role": "user", "content": compact_prompt}]).strip()
        except Exception:
            return None
        if not summary:
            return None
        return [{"role": "user", "content": f"[对话摘要] {summary}"}] + recent

    @staticmethod
    def _truncate_recent(
        history: list[dict[str, str]], keep_recent_chars: int
    ) -> list[dict[str, str]]:
        recent: list[dict[str, str]] = []
        used = 0
        for msg in reversed(history):
            need = len(msg["content"])
            if used + need > keep_recent_chars and recent:
                break
            recent.append(msg)
            used += need
        recent.reverse()
        return recent

    @staticmethod
    def _format_for_compact(messages: list[dict[str, str]]) -> str:
        return "\n".join(f"{m['role']}: {m['content']}" for m in messages)

    # ---- 解析 ----

    def _parse(self, raw: str) -> contracts.Action | None:
        """按 OpenClaw 思路：名字允许清单 + payload 上限 + 契约分类。"""
        return json_repair.repair_action(
            raw,
            allowed_actions=set(self.registry.names()),
        )
