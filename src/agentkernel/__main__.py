"""CLI 入口：`python -m agentkernel` 启动交互式对话。

内置命令（以 `/` 开头）：
- /new [标题]   新建会话并切换过去
- /sessions     列出最近会话
- /history      查看当前会话历史
- /help         查看帮助
- /quit         退出（同 quit / exit / q）
"""
from __future__ import annotations

import argparse
import uuid

from agentkernel.memory.sqlite_store import SQLiteStore, default_store
from agentkernel.runtime.agent import Agent
from agentkernel.tools import builtin
from agentkernel.tools.registry import Registry


def _print_help() -> None:
    print(
        "内置命令：/new [标题] | /sessions | /history | /help | /quit\n"
        "其他输入都会交给 Agent 处理。"
    )


def _load_history(store: SQLiteStore, session_id: str) -> list[dict[str, str]]:
    return store.get_messages(session_id)


def _build_agent() -> tuple[Agent, Registry]:
    registry = Registry()
    builtin.register_builtin(registry)
    return Agent(registry), registry


def _repl(store: SQLiteStore) -> None:
    agent, _ = _build_agent()
    session_id = "default"
    store.create_session(session_id)

    print("AgentKernel 已启动（/help 查看内置命令，Ctrl+C 中断）")
    history: list[dict[str, str]] = _load_history(store, session_id)

    while True:
        try:
            user_input = input("你 > ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n再见")
            break

        if not user_input:
            continue

        if user_input.startswith("/"):
            cmd, _, arg = user_input[1:].partition(" ")
            cmd = cmd.lower()
            if cmd in ("quit", "q", "exit"):
                print("再见")
                break
            if cmd == "help":
                _print_help()
                continue
            if cmd == "new":
                session_id = uuid.uuid4().hex[:8]
                store.create_session(session_id, arg.strip() or session_id)
                history = _load_history(store, session_id)
                print(f"已新建会话 {session_id}（历史已清空）")
                continue
            if cmd == "sessions":
                sessions = store.list_sessions()
                if not sessions:
                    print("（暂无会话）")
                for s in sessions:
                    mark = "← 当前" if s["id"] == session_id else ""
                    print(f"- {s['id']}  {s['title']}  （更新于 {s['updated_at'][:19]}）{mark}")
                continue
            if cmd == "history":
                msgs = store.get_messages(session_id)
                if not msgs:
                    print("（当前会话暂无历史）")
                for m in msgs:
                    who = "你" if m["role"] == "user" else "Agent"
                    print(f"{who} > {m['content']}")
                continue
            print(f"未知命令 /{cmd}，输入 /help 查看帮助")
            continue

        # 普通输入：先持久化用户消息，再跑 Agent，最后持久化最终回答。
        store.append_message(session_id, "user", user_input)
        print("Agent > ", end="", flush=True)
        try:
            reply = agent.run(user_input, history)
        except Exception as e:  # 模型失败等不应打断 CLI
            reply = f"[AgentKernel 错误] {type(e).__name__}: {e}"
        print(reply)
        store.append_message(session_id, "assistant", reply)
        # 以 DB 的干净历史为准：内部 ReAct 观察信息不落库，避免污染后续上下文。
        history = _load_history(store, session_id)


def main() -> None:
    parser = argparse.ArgumentParser(description="AgentKernel CLI")
    parser.add_argument(
        "--db",
        default=None,
        help="SQLite 库文件路径（默认 ~/.agentkernel/agentkernel.db，可用 :memory:）",
    )
    args = parser.parse_args()

    store = default_store() if args.db is None else SQLiteStore(args.db)
    try:
        _repl(store)
    finally:
        store.close()


if __name__ == "__main__":
    main()
