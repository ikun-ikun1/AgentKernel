"""ReAct 主循环：思考 → 行动 → 观察 → 回复，带上下文管理（截断/压缩后续补）。"""
from __future__ import annotations
from typing import Any

from agentkernel.tools import contracts, json_repair
from agentkernel.tools.registry import Registry
from agentkernel.runtime import llm

SYSTEM_PROMPT = """你是一个能调用工具的 Agent。

回答规则（严格遵守，只输出 JSON，不要输出其他内容）：
- 如果需要用工具，输出：
  {"action": "工具名", "action_input": {"参数": "值"}}
- 如果已经能回答用户，输出：
  {"action": "final_answer", "action_input": "你的回答内容"}

可用工具：
{tools}
"""


class Agent:
    def __init__(self, registry: Registry, max_steps: int = 10) -> None:
        self.registry = registry
        self.max_steps = max_steps

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
                history.append({"role": "user", "content": f"工具 {action.action} 返回：{result}"})
                continue  # 回到循环，让模型基于观察结果继续

            # 解析失败 → 降级为纯文本回答
            history.append({"role": "assistant", "content": raw})
            return raw

        return "（达到最大步数上限，未完成）"

    def _build_messages(self, history: list[dict[str, str]]) -> list[dict[str, str]]:
        system = SYSTEM_PROMPT.format(tools=self.registry.describe())
        return [{"role": "system", "content": system}] + history

    @staticmethod
    def _parse(raw: str) -> contracts.Action | None:
        obj = json_repair.parse_json(raw)
        if obj is None:
            return None
        return contracts.classify(obj)
