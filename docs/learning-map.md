# AgentKernel 教学映射（agent-study ↔ OpenClaw ↔ Workbench）

本文档把 AgentKernel 的每个模块映射到本地学习资料的具体章节，方便「边读源码、边对教学点、边准备面试」。

## 1. 总览：三条资料线如何互补

| 资料 | 定位 | AgentKernel 怎么用 |
|------|------|-------------------|
| `agent-study-main` | 教学课程（Ch0-Ch15），讲原理 + 面试高频 | 每章对应一个模块，见下表 |
| `openclaw` | 工业级开源 Agent（TypeScript） | 借鉴 `packages/tool-call-repair` 的分层设计 |
| `ai-agent-workbench-main` | 实习项目（Claude Agent SDK 搭业务平台） | 作为应用层对照，明确 SDK Runtime 与自实现 Runtime 的边界 |

## 2. 模块 ↔ 教学章节映射

| AgentKernel 模块 | agent-study 章节 | 核心教学点 | 面试高频问题 |
|-----------------|-----------------|-----------|-------------|
| `runtime/agent.py` | Ch2（核心组件）、Ch3（Agent 类型） | ReAct 循环：思考 → 行动 → 观察 → 回复；三种记忆（短期/长期/工作） | ReAct 和 Plan-Execute 区别？上下文太长为什么忘事？ |
| `tools/contracts.py` + `tools/json_repair.py` | Ch11（Tool Calling 底层） | **LLM 不是「调用函数」，只是输出 JSON，代码解析并执行**；脏 JSON 修复 | 工具调用失败/坏 JSON 怎么办？ |
| `tools/registry.py` | Ch2（工具设计）、Ch11 | 工具注册、JSON Schema 校验、错误回灌 | 工具参数怎么校验？工具报错怎么处理？ |
| `runtime/llm.py` | Ch11（Token 原理） | 工具定义消耗 token；模型只返回文本 | 工具描述计入 prompt token 吗？ |
| `memory/sqlite_store.py` | Ch14（SQLite + Agent 存储） | 用最小持久化适配器验证消息/观察恢复 | Runtime 为什么需要状态存储？WAL 是什么？ |
| `rag/ingest.py` | Ch9（RAG 深潜） | 文档指纹、增量索引、FTS5、向量召回、混合排序和来源引用 | 如何保证重建幂等？词法/向量如何融合？引用如何可追踪？ |
| `mcp/client.py` + `mcp/server.py` | Ch10（MCP 协议） | JSON-RPC 2.0；stdio 传输；`initialize → tools/list → tools/call` | MCP 为什么不是 REST？stdio 和 SSE 区别？ |
| `mcp/framing.py` | Ch10.6（传输层） | Content-Length 帧；日志走 stderr | stdio 生产陷阱？ |

## 3. 按学习顺序的走读路径

### 第一步：理解「模型只输出文本」——Ch11 + `tools/contracts.py`

读 `agent-study-main/chapter_11_tool_calling/11_tool_calling_deepdive.py` 的 11.1：
> 误解：「LLM 调用了我的函数」；真相：「LLM 输出了一个 JSON 对象，你的代码解析了它并执行了函数」。

对应代码：
- `SYSTEM_PROMPT` 约定固定 JSON 协议：`{"action": ..., "action_input": ...}`
- `contracts.classify()` 把 dict 分类成 `ToolCall` / `FinalAnswer`，名字必须命中允许清单
- `Agent.run()` 收到 `ToolCall` 后才调 `registry.run()` —— **执行权在代码手里，不在模型手里**

### 第二步：脏 JSON 怎么办——OpenClaw + `tools/json_repair.py`

读 `openclaw/packages/tool-call-repair/src/`：
- `contracts.ts`：解析选项（allowlist、maxPayloadBytes）
- `payload.ts`：从文本中扫描出工具调用块
- `promote.ts`：把纯文本调用「晋升」为结构化调用

对应代码：`json_repair.py` 三层修复 + `repair_action()`；`Agent._parse()` 传入 `allowed_actions=registry.names()`。
关键词：**工具名允许清单、payload 上限、晋升/降级**。

### 第三步：工具注册与参数校验——Ch2 + `tools/registry.py`

读 `agent-study-main/chapter_02_components/02_agent_components.py` 的 2.3（工具设计）。
对应代码：`registry.validate_parameters()`（纯 Python JSON Schema 子集）+ `describe()` 生成给模型的工具描述。

### 第四步：上下文与记忆——Ch2 + Ch14 + `memory/sqlite_store.py`

读 Ch2 的记忆分类（短期/长期/工作），Ch14 的 schema 设计。
对应代码：
- 短期记忆 = `Agent.run(history)` 里的消息列表
- 工作记忆 = 工具观察回灌（`工具 X 返回：...`）
- 长期记忆 = SQLite `sessions/messages/tool_logs`
- 上下文限制 = `ContextConfig` + `_truncate` / `_try_compact`

### 第五步：MCP 两端——Ch10 + `mcp/`

读 `agent-study-main/chapter_10_mcp/10_mcp_deepdive.py`：
- 10.2 三层架构（Host/Client/Server）
- 10.3 JSON-RPC 2.0（id 匹配、错误码）
- 10.6 stdio 传输与生产陷阱

对应代码：
- `mcp/framing.py`：Content-Length 帧协议（日志走 stderr）
- `mcp/server.py`：`KnowledgeMCPServer`（纯 Python）+ `handle_json_rpc()` + `run_stdio()`
- `mcp/client.py`：`StdioMCPClient`（自实现 `initialize → tools/list → tools/call`）
- `mcp/server.py` 的 `main()` 可被 `python -m agentkernel.mcp.server` 启动为真实子进程

### 第六步：RAG——Ch9 + `rag/ingest.py`

读 `agent-study-main/chapter_09_rag_deepdive/09_rag_deepdive.py`。
对应代码：`load_document_parts` / `chunk_text` / `SQLiteIndex` / `_VectorIndex` / `KnowledgeBase`。

## 4. 与实习项目互补的讲述逻辑

1. **问题**：实习用 Claude Agent SDK 搭工作台，主循环/工具调用/上下文全被框架封装，面试讲不清底层。
2. **做法**：个人项目不套框架，从零实现最小 ReAct、工具调用契约、JSON 修复、上下文策略和 MCP 两端，并用检索样例验证外部状态接入；Workbench 负责直接使用 SDK 把能力编排成业务产品。
3. **证据**：单元测试和 `eval.py` 能验证工具调用、坏 JSON、上下文压缩、MCP stdio 链路、增量入库和持久化检索。
4. **互补**：Workbench 证明「会用框架交付业务」，AgentKernel 证明「能拆解、实现并验证 Runtime 底层机制」。

## 5. 深挖问答自查清单

- [ ] 能画出 ReAct 循环的数据流，并指出 MAX_STEPS 防死循环
- [ ] 能解释「模型输出 JSON → 代码解析 → 执行」三层协议
- [ ] 能说清坏 JSON 三层修复各层的边界，以及为什么需要工具名允许清单
- [ ] 能说清 truncate 和 compact 的区别，以及 compact 失败怎么降级
- [ ] 能说清 SQLite 三张表的关系，WAL 和 foreign_keys 的作用
- [ ] 能说清 MCP 的 `initialize → tools/list → tools/call` 流程和 stdio 帧格式
- [ ] 能说清知识库问答「带来源」的实现位置（`SearchResult.to_citation()`）
