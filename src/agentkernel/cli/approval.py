"""CLI 人工审批回调（P0-1）。

不是 Registry 依赖：只由 composition 注入给 Agent；非交互/EOF/超时一律拒绝。
"""

from __future__ import annotations

import select
import sys
from collections.abc import Callable

from agentkernel.application.tool_executor import ApprovalRequest


class ConsoleApproval:
    reviewer = "user"

    def __init__(
        self,
        *,
        input_fn: Callable[[str], str] | None = None,
        output_fn: Callable[[str], None] = print,
        timeout_seconds: float | None = 30.0,
        interactive: bool | None = None,
    ) -> None:
        self._input = input_fn or input
        self._output = output_fn
        self._timeout = timeout_seconds
        self._interactive = sys.stdin.isatty() if interactive is None else interactive

    def __call__(self, request: ApprovalRequest) -> bool:
        if not self._interactive:
            return False
        self._output(
            f"\n[审批] 工具 {request.tool_name} 请求执行\n"
            f"参数摘要：{request.summary}\n"
            f"会话：{request.session_id or '-'}｜幂等键：{request.idempotency_key}\n"
        )
        try:
            if self._timeout is not None and self._input is input and sys.stdin.isatty():
                ready, _, _ = select.select([sys.stdin], [], [], self._timeout)
                if not ready:
                    return False
            answer = self._input("批准执行? [y/N] ")
        except (EOFError, KeyboardInterrupt, TimeoutError, OSError, ValueError):
            return False
        return answer.strip().lower() in {"y", "yes"}
