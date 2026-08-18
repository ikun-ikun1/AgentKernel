"""工具调用协议契约（借鉴 OpenClaw tool-call-repair 的 contracts.ts）。

定义合法的工具调用 JSON 结构，例如：
  {"action": "工具名", "action_input": {...}}
  {"action": "final_answer", "action_input": "文本"}
"""
