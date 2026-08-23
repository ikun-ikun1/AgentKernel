"""ReAct 主循环：思考 → 行动 → 观察 → 回复，带上下文管理。

上下文管理策略（个人项目特点：无框架、无 tokenizer，按字符预算工程化实现）：
- truncate：超预算时保留「首条用户要求 + 最近消息」，防止第 10 轮把第 1 轮要求丢了。
- compact：优先调模型做摘要压缩，把旧历史压成一条「对话摘要」；模型不可用时降级为 truncate。
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Callable

from agentkernel.runtime import llm
from agentkernel.tools import contracts, json_repair
from agentkernel.tools.registry import Registry

SYSTEM_PROMPT = """你是一个能调用工具的 Agent。

回答规则（严格遵守，只输出 JSON，不要输出其他内容）：
- 如果需要用工具，输出：
  {"action": "工具名", "action_input": {"参数": "值"}}
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
    max_history_chars: int = 8000        # 送入模型的历史消息字符上限
    compact_trigger_chars: int = 6000     # 超过该值触发 compact 压缩
    keep_recent_chars: int = 2000         # compact 时保留的最近消息字符数


# 工具调用观察者：在每次工具执行后回调，用于审计日志等（对应 agent-study Ch14 tool_logs）
ToolObserver = Callable[[str, dict[str, Any], str], None]


class Agent:
    def __init__(
        self,
        registry: Registry,
        max_steps: int = 10,
        context: ContextConfig | None = None,
        on_tool_call: ToolObserver | None = None,
    ) -> None:
        self.registry = registry
        self.max_steps = max_steps
        self.context = context or ContextConfig()
        self.on_tool_call = on_tool_call

    def run(self, user_input: str, history: list[dict[str, str]]) -> str:
        """跑一轮对话，就地更新 history。返回最终回答。"""
        history.append({"role": "user", "content": user_input})

        for _ in range(self.max_steps):
            raw = llm.chat(self._build_messages(history))
            action = self._parse(raw)

            if isinstance(action, contracts.FinalAnswer):
                history.append({"role": "assistant", "content": action.text})
                return action.text

            if isinstance(action, contracts.ToolCall):
                history.append({"role": "assistant", "content": raw})
                result = self.registry.run(action.action, action.action_input)
                if self.on_tool_call is not None:
                    try:
                        self.on_tool_call(action.action, action.action_input, result)
                    except Exception:
                        pass  # 审计失败不影响主流程
                history.append(
                    {"role": "user", "content": f"工具 {action.action} 返回：{result}"}
                )
                continue  # 回到循环，让模型基于观察结果继续

            # 解析失败 → 降级为纯文本回答（OpenClaw：不能晋升为工具调用就当普通文本）
            history.append({"role": "assistant", "content": raw})
            return raw

        return "（达到最大步数上限，未完成）"

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
        budget = self.context.max_history_chars - (
            len(first_user["content"]) if first_user else 0
        )
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
            compact_prompt = COMPACT_PROMPT.replace(
                "{history}", self._format_for_compact(older)
            )
            summary = llm.chat(
                [{"role": "user", "content": compact_prompt}]
            ).strip()
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
