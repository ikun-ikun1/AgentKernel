# AgentKernel 自我审查报告

> 对比对象：Claude Agent SDK（以本地 `ai-agent-workbench` 用法为样本）、GitHub 高星 MCP 库（`modelcontextprotocol/python-sdk`、`mark3labs/mcp-go`、官方 `modelcontextprotocol/servers`）、本地 `agent-study` 的简化教学设计。
> 目的：找出「教学版内核」与工业级实现的差距，能落地的落地，不能落地的说清楚为什么不。

## 阅读前提：两个项目不是同类产品

本报告的对照对象分工如下：

- AI Agent Workbench：应用层项目，负责 Web、业务 Agent、CLI/MCP 工具接入、人工审批、审计和用户会话。
- AgentKernel：Runtime/协议实验，负责解释 ReAct、Tool Calling、上下文策略和 MCP wire protocol。

AgentKernel 中的 MySQL 主存储、SQLite 测试适配器、检索样例和 CLI 属于研究实现与验证入口；它不替代 Workbench 的业务 RAG 编排、会话、审批或审计产品。以下对比只比较底层机制，不比较产品功能数量。

## 1. 与 Claude Agent SDK 对比

Workbench 实习项目用 `claude_agent_sdk`：主循环/工具调用/权限回调/审批全部由 SDK 托管。AgentKernel 反向把每个环节手写出来：

| Claude Agent SDK 能力 | AgentKernel 现状 | 评价 |
|----------------------|-----------------|------|
| 工具 schema 原生传给模型 | prompt 注入工具描述 + JSON Schema 校验 | ✅ 教学目的达到；token 成本更高，但可解释 |
| `can_use_tool` 权限回调 | AgentKernel 不实现企业审批回调；仅保留工具名 allowlist、只读示例和无 shell | ❌ 有意不做，避免复制 Workbench 治理层 |
| `mcp_servers` 配置接入外部 MCP | **本次新增 `--mcp`**，可接任意 stdio MCP server，工具名前缀 `mcp<N>_` 防冲突 | ✅ 对齐 |
| 工具结果自动回灌 | ReAct 观察回灌 | ✅ 已有 |
| 上下文管理 | truncate + compact | ✅ 已有（SDK 对用户是黑盒） |
| 流式输出 / 子代理 / 审批卡片 | 不做 | ❌ 超出 CLI 教学原型范围，文档说明即可 |
| 审计日志 | MySQL `tool_logs`（SQLite 仅作测试适配）用于观察 Runtime 工具调用 | ⚠️ 不是 Workbench 的审计产品替代品 |

**本次改进**：CLI `--mcp` 外部 MCP server 接入，用 `mcp<N>_` 前缀避免工具名冲突；该功能用于验证协议互操作，不是建设 MCP 管理平台。

## 2. 与 GitHub 高星 MCP 库对比

高星库核心特性：官方 Python SDK（FastMCP、stdio/SSE/Streamable HTTP）、`mcp-go`（Go 实现、类型安全）、官方 servers（文件系统/GitHub 等现成 server）。

| 特性 | AgentKernel 现状 | 说明 |
|------|-----------------|------|
| JSON-RPC 2.0 | ✅ 自实现 client + server | `id` 匹配、错误码 -32700/-32601/-32602/-32603 |
| stdio 帧协议 | ✅ `mcp/framing.py`（Content-Length） | 对齐官方传输 |
| `initialize` 能力协商 | ✅ **本次增强**：client 校验 `protocolVersion` 并保存 `serverInfo` | 之前只发不校验 |
| `tools/list` / `tools/call` | ✅ | — |
| `structuredContent` 返回 | ✅ **本次增强**：`tools/call` 结果优先 content，退化到 structuredContent | 对齐 2025-06-18 规范 |
| 工具名前缀防冲突 | ✅ **本次增强**：`register_mcp_tools(prefix=...)` | 对齐 `mcp__server__tool` 惯例 |
| Resources / Prompts / Sampling 原语 | ❌ 不实现 | 教学版只做 Tools 原语，面试能讲边界即可 |
| SSE / Streamable HTTP | ❌ 不实现 | 本地 CLI 场景 stdio 是唯一正解（Ch10.6 决策树） |
| 分页 / 进度通知 | ❌ 不实现 | 个人项目工具结果小，不需要；文档说明 |
| 多工具并行调用 | ✅ **本次新增**：协议支持 `{"actions":[...]}`，当前串行执行 | 对齐 Ch11 Parallel Tool Calling 概念 |

**本次改进**：初始化协商校验、`structuredContent` 兼容、工具名前缀、多工具调用协议。

## 3. 与 agent-study 简化设计对比

| agent-study 章节 | 简化设计 | AgentKernel 落地 |
|-----------------|---------|-----------------|
| Ch2 组件/记忆 | 短期/长期/工作记忆概念 | 短期=消息列表，工作=观察回灌，长期=MySQL |
| Ch10 MCP | `SimulatedMCPServer` 行分隔 JSON | 升级为 Content-Length 帧 + 标准 JSON-RPC |
| Ch11 Tool Calling | 讲 Parallel/Streaming/Strict | 新增多工具调用；流式/严格模式不实现（非流式 prompt 协议） |
| Ch14 数据库存储 | 5 张表 + 连接池 | 精简为 3 张 Runtime 表（sessions/messages/tool_logs），MySQL 负责生产持久化，够用且可讲 |

## 4. 已知差距与取舍

| 差距 | 为什么不现在做 |
|------|---------------|
| 流式输出/流式工具调用 | 当前 DeepSeek 走 OpenAI 非流式接口；CLI 演示不需要 |
| Parallel Tool Calling 真并行 | 教学版串行更易解释观察回灌顺序；文档已注明可扩展线程池 |
| Resources/Prompts/Sampling | 面试能讲清原语边界即可，不做伪实现 |
| SSE/Streamable HTTP | Ch10.6 决策树：本地 stdio 唯一正解 |
| 动态工具选择（省 token） | 工具 < 10 个，固定全量注册可接受；面试可讲思路 |
| 完整 JSON Schema（$ref/anyOf） | 手写校验器覆盖工具所需子集，够用且是教学点 |

## 5. 问题驱动的优化清单

1. `tools/contracts.py`：在 ReAct 基线之上增加 `ToolCalls`（`{"actions":[...]}`）多工具调用契约
2. `runtime/agent.py`：支持多工具调用顺序执行 + 提取 `_execute_tool_call` 复用观察者钩子
3. `tools/json_repair.py`：在基础 JSON 解析之上增加结构提取、分层修复、允许清单和 payload 上限，覆盖多工具数组
4. `mcp/client.py`：`initialize` 能力协商校验 + `structuredContent` 兼容 + `register_mcp_tools(prefix=...)`
5. `__main__.py`：新增 `--mcp` 接入外部 stdio MCP server（自动替换 `python` 为当前解释器）
6. `tools/registry.py` + `builtin.py`：工具描述增强（enum/default/description 注入 prompt）
7. 测试：新增多工具调用、前缀注册、structuredContent、协商断言等 5 个用例，并覆盖异常输入与降级路径

这些改动的价值不在于功能数量，而在于针对两个具体问题改变默认行为：模型输出不可靠时不盲目执行，检索依赖或文档内容变化时不丢失已有索引。面试时应把“参考 agent-study 复现”作为学习基线，把“分层修复、边界校验、增量更新和可回退检索”作为优化与创新重点。

## 6. 复查结论

AgentKernel 作为「Runtime/协议研究与验证原型」的定位是准确的：**主链路完整、与 Workbench 分层、能解释取舍**。与工业级 SDK/MCP 库的差距集中在流式、多原语、分布式部署和企业治理；这些不是本项目目标。面试时应强调：Workbench 证明「会用框架交付业务」，AgentKernel 证明「能实现关键底层机制并理解框架边界」。
