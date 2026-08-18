"""CLI 入口：`python -m agentkernel` 启动交互式对话。"""
from __future__ import annotations

from agentkernel.runtime.agent import Agent
from agentkernel.tools import builtin
from agentkernel.tools.registry import Registry


def main() -> None:
    registry = Registry()
    builtin.register_builtin(registry)
    agent = Agent(registry)

    print("AgentKernel 已启动（输入 quit 退出，Ctrl+C 中断）")
    history: list[dict[str, str]] = []
    while True:
        try:
            user_input = input("你 > ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n再见")
            break
        if not user_input:
            continue
        if user_input.lower() in ("quit", "exit", "q"):
            print("再见")
            break
        print("Agent > ", end="", flush=True)
        reply = agent.run(user_input, history)
        print(reply)


if __name__ == "__main__":
    main()
