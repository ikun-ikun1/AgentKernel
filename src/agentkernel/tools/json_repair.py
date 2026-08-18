"""非法 JSON 三层修复（借鉴 OpenClaw tool-call-repair 的分层思想）：
1. 提取（payload）：从文本里抠出 { ... } 片段
2. 修复（promote）：补括号 / 修引号逗号，升级为合法 JSON
3. 降级：三次失败 → 把原始输出当普通回复
"""
