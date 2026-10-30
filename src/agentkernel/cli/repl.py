"""交互式 REPL（A1）：命令分发与消息持久化。

行为契约：提示符、命令集合、输出文案、错误兜底与拆分前一致。
"""

from __future__ import annotations

import uuid

from agentkernel.cli.composition import ingest_path
from agentkernel.memory.base import RuntimeStore
from agentkernel.rag.ingest import KnowledgeBase
from agentkernel.runtime.agent import Agent
from agentkernel.utils import observability


def print_help() -> None:
    print(
        "内置命令：/new [标题] | /sessions | /history | /ingest <路径> | /docs | /logs | /help | /quit\n"
        "其他输入都会交给 Agent 处理。"
    )


def load_history(store: RuntimeStore, session_id: str) -> list[dict[str, str]]:
    return store.get_messages(session_id)


def run_repl(store: RuntimeStore, kb: KnowledgeBase, agent: Agent) -> None:
    session_id = "default"
    store.create_session(session_id)

    def _log_tool_call(tool_name: str, action_input: dict[str, object], result: str) -> None:
        # Registry returns a str-compatible result carrying explicit status.
        ok = getattr(result, "success", not result.startswith("[工具"))
        store.log_tool_call(
            session_id,
            tool_name,
            action_input,
            result,
            ok,
            duration_ms=getattr(result, "duration_ms", None),
        )

    agent.on_tool_call = _log_tool_call
    agent.session_id = session_id
    agent.on_event = lambda event: observability.emit(
        event["event"], **{k: v for k, v in event.items() if k != "event"}
    )

    print("AgentKernel 已启动（/help 查看内置命令，Ctrl+C 中断）")
    history: list[dict[str, str]] = load_history(store, session_id)

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
                print_help()
                continue
            if cmd == "new":
                session_id = uuid.uuid4().hex[:8]
                store.create_session(session_id, arg.strip() or session_id)
                history = load_history(store, session_id)
                agent.session_id = session_id
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
            if cmd in ("ingest", "kb"):
                if not arg.strip():
                    print("用法：/ingest <文件或目录路径>")
                    continue
                ingest_path(kb, arg.strip())
                continue
            if cmd == "docs":
                docs = kb.list_documents()
                if not docs:
                    print("（知识库为空，用 /ingest <路径> 入库文档）")
                for doc in docs:
                    print(f"- {doc}")
                continue
            if cmd == "logs":
                logs = store.list_tool_logs(session_id)
                if not logs:
                    print("（当前会话暂无工具调用记录）")
                for log in logs:
                    status = "成功" if log["success"] else "失败"
                    created = str(log.get("created_at", ""))[:19]
                    tool_name = str(log.get("tool_name", ""))
                    duration = log.get("duration_ms")
                    duration_text = (
                        f" {duration:.1f}ms" if isinstance(duration, (int, float)) else ""
                    )
                    print(
                        f"- {created} {tool_name} {status}{duration_text}\n"
                        f"  入参：{log.get('input_json', '')}\n"
                        f"  结果：{str(log.get('output_json', ''))[:120]}"
                    )
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
        history = load_history(store, session_id)
