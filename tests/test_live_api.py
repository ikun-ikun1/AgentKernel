"""真实 API 冒烟测试（默认排除，用 `make test-live` 显式运行）。

只做 1 次调用（成本约 $0.0002），断言四件事：
1. 回答包含期望数字；
2. tokens 非空；
3. cost_usd 非空且 > 0，并写入定价表版本；
4. span/turn 事件结构正常。

未设置 `AGENTKERNEL_LIVE_API=1` 或缺 `DEEPSEEK_API_KEY` 时 skip；
CI 默认不跑（`make test` 带 `-m "not live"`），因此不影响 0-skip 门禁。
"""

from __future__ import annotations

import os

import pytest

from agentkernel.runtime.agent import Agent
from agentkernel.tools import builtin
from agentkernel.tools.registry import Registry
from agentkernel.utils import env as env_utils
from agentkernel.utils import observability as obs

env_utils.load_env()

_LIVE_ENABLED = os.environ.get("AGENTKERNEL_LIVE_API") == "1"
_HAS_KEY = bool(os.environ.get("DEEPSEEK_API_KEY"))
pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        not (_LIVE_ENABLED and _HAS_KEY),
        reason="设置 AGENTKERNEL_LIVE_API=1 且提供 DEEPSEEK_API_KEY 才跑",
    ),
]


def test_live_turn_records_usage_and_cost() -> None:
    events: list[dict] = []
    registry = Registry()
    builtin.register_builtin(registry)
    agent = Agent(registry, on_event=events.append, session_id="live-smoke")

    reply = agent.run("只回答一个数字：6*7 等于几？用 final_answer 输出。", [])

    assert "42" in reply, f"模型回答不符合预期：{reply!r}"
    turn = [event for event in events if event["event"] == "turn"][-1]
    assert turn["success"] is True
    assert turn["tokens"] is not None
    assert turn["tokens"]["in"] > 0 and turn["tokens"]["out"] > 0
    assert turn["cost_usd"] is not None and turn["cost_usd"] > 0
    assert turn["pricing_table_version"] == obs.PRICING_TABLE_VERSION
    assert turn["span"]["name"] == "turn"
    assert turn["error_type"] is None
    print(
        f"\nlive turn: model={turn['model']} tokens={turn['tokens']} "
        f"cost_usd={turn['cost_usd']} latency_ms={turn['latency_ms']}"
    )
