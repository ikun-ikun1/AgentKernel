# ADR-003：生产级模块边界与增量重构（架构 A0）

## 状态

Accepted（A0→A6 完成；A7.1 LLM 端口已接线，A7.2–A7.4 进行中；旧 import shim 保留一个版本后删除，不改变 CLI/schema/安全/D4 语义）

## 背景

AgentKernel 目前是「能跑、能测、能交付」的 CLI 研究原型，但代码结构仍偏单体：

| 文件 | 行数 | 当前职责 | 问题 |
|---|---:|---|---|
| `src/agentkernel/__main__.py` | 392 | argparse、env 加载、依赖装配、REPL、历史加载、文档入库、帮助、DSN 脱敏 | 组合根与交互逻辑混在一起，换 CLI/嵌入方式要改主文件 |
| `src/agentkernel/runtime/agent.py` | 475 | ReAct 循环、上下文策略、工具执行、事件组装、解析 | 一个类同时承担编排、策略、I/O 事件与协议解析 |
| `src/agentkernel/rag/ingest.py` | 659 | 文档加载、分块、Shingle、SQLite 索引、向量索引、KnowledgeBase 编排 | 领域模型、存储适配器、检索策略、文件 I/O 混在一个文件 |
| `src/agentkernel/memory/mysql_store.py` | 337 | 连接、事务、行锁、SQL、redact、截断 | 存储适配器承担了部分策略；换存储会复制逻辑 |
| `src/agentkernel/mcp/server.py` | 245 | JSON-RPC 处理、stdio transport、知识库工具 | 协议、传输、业务处理器耦合，难单独测试 |
| `src/agentkernel/mcp/client.py` | 246 | stdio transport、JSON-RPC client、工具注册 | 传输与工具桥接耦合 |
| `src/agentkernel/utils/env.py` | 90 | 环境变量读取、默认值、校验 | 全局读取分散，测试需要 monkeypatch 环境 |

这不是「为了架构而架构」。生产化需要的是：**领域逻辑可单测、外设可替换、故障可隔离、组合根可审计**。当前测试已经证明行为，但继续加功能会放大耦合成本。

## 决策

采用**务实的 ports & adapters（六边形）**，但只对真实外部边界抽象，不引入 DI 框架、不重写异步、不做多租户平台。

### 目标模块

```text
src/agentkernel/
├─ domain/                 # 纯领域：无 I/O、无 env、无 SQL、无 HTTP
│  ├─ models.py            # Session / Message / ToolCall / Chunk / SearchResult
│  ├─ errors.py            # 领域错误与错误码
│  └─ context_policy.py    # 上下文预算/截断/压缩策略（纯函数）
├─ application/            # 用例编排：只依赖 domain + ports
│  ├─ run_turn.py          # 一轮 ReAct：LLM → 解析 → 工具 → 观察 → 回复
│  ├─ ingest_document.py   # 文档入库用例
│  ├─ query_knowledge.py   # 检索用例
│  └─ manage_session.py    # 会话/历史/日志用例
├─ ports/                  # Protocol：外部能力接口
│  ├─ llm.py               # LLMClient
│  ├─ runtime_store.py     # RuntimeStore（现有 memory/base.py 升级）
│  ├─ knowledge_store.py   # KnowledgeStore
│  ├─ tool_runtime.py      # ToolRuntime / ToolRegistry 接口
│  ├─ event_sink.py        # EventSink（JSONL/trace/成本）
│  └─ mcp_transport.py     # MCPTransport（stdio/HTTP 可替换）
├─ adapters/               # 具体实现：只依赖 ports + domain
│  ├─ llm/openai_compatible.py
│  ├─ memory/mysql_store.py
│  ├─ memory/sqlite_store.py
│  ├─ knowledge/mysql_ngram.py
│  ├─ knowledge/chroma_vector.py
│  └─ mcp/stdio_transport.py
├─ cli/                    # 组合根 + 交互
│  ├─ main.py              # argparse、退出码、错误呈现
│  ├─ repl.py              # /new /history /ingest /quit
│  └─ composition.py       # 读配置、选适配器、装配依赖
├─ config/
│  └─ settings.py          # 类型化配置；env 解析集中在这里
├─ observability/          # JSONL、trace、redaction、pricing、report
└─ protocol/               # MCP framing / JSON-RPC 纯协议
```

### 依赖规则（必须可自动检查）

```text
domain        ← application ← ports
                     ↑
                 adapters
                     ↑
                   cli（composition root）

禁止：
- domain 不得 import adapters / cli / sqlite3 / pymysql / requests / openai
- application 不得 import adapters / cli
- ports 不得 import adapters / cli
- adapters 不得 import cli
- cli 可以做所有装配，但不含业务分支
```

建议用 `tests/test_architecture.py` 做 AST/import 断言（不新增 `import-linter` 依赖），例如：扫描 `domain/**/*.py` 的 import，出现 `agentkernel.adapters`、`sqlite3`、`pymysql`、`openai` 即失败。

### 当前文件 → 目标模块

| 当前 | 目标 |
|---|---|
| `__main__.py` | `cli/main.py` + `cli/repl.py` + `cli/composition.py` |
| `runtime/agent.py` | `application/run_turn.py` + `domain/context_policy.py` + `runtime/tool_executor.py` + `observability/events.py` |
| `runtime/llm.py` | `ports/llm.py` + `adapters/llm/openai_compatible.py` |
| `memory/base.py` | `ports/runtime_store.py`（保留 shim 兼容旧 import） |
| `memory/mysql_store.py` | `adapters/memory/mysql_store.py` + `domain/models.py` |
| `memory/sqlite_store.py` | `adapters/memory/sqlite_store.py` |
| `rag/ingest.py` | `domain/knowledge.py` + `rag/loaders.py` + `rag/chunking.py` + `rag/indexes.py` + `application/query_knowledge.py` |
| `rag/mysql_store.py` | `adapters/knowledge/mysql_ngram.py` |
| `mcp/framing.py` | `protocol/mcp_framing.py` |
| `mcp/client.py` | `adapters/mcp/stdio_transport.py` + `application/mcp_tools.py` |
| `mcp/server.py` | `adapters/mcp/knowledge_server.py`（transport 与 handler 分离） |
| `mcp/profiles.py` | `config/mcp_profiles.py` |
| `tools/*` | `domain/tool_contracts.py` + `adapters/tools/builtin.py` + `runtime/tool_registry.py` |
| `utils/observability.py` | `observability/{events,redact,pricing,report}.py` |
| `utils/env.py` | `config/settings.py` |

## 增量实施（每步行为不变、可独立回滚）

| 切片 | 内容 | 验收 |
|---|---|---|
| **A0** | 本 ADR + 目标图 + 依赖规则 + 生产问题叙事 | 文档评审通过；不改代码 |
| **A1** | 抽 `config/settings.py` 与 `cli/composition.py`；`__main__.py` 变薄；REPL 移到 `cli/repl.py` | ✅ 已完成：`cli/{main,repl,composition}.py` + `config/settings.py`；181 tests 全绿；CLI help/smoke/退出码 2 不变；`__main__.py` 仅入口 + 兼容别名 |
| **A2** | `RuntimeStore` 移到 ports；MySQL/SQLite 移到 adapters；保留旧路径 shim | ✅ 已完成：`ports/runtime_store.py` + `adapters/memory/{mysql,sqlite}_store.py`；旧 `memory/{base,mysql_store,sqlite_store}.py` 为 shim；真实 MySQL 180 passed（D4 20×20 绿）、本地 make check 绿 |
| **A3** | `LLMClient`、`EventSink` port；OpenAI 适配器；事件组装从 Agent 拆出 | ✅ 已完成：`ports/llm.py` + `adapters/llm/openai_compatible.py`（旧 `runtime/llm.py` shim）；事件组装移到 `observability/events.py`；边界拆分完成，LLM 真正注入 Agent 在 A7.1；JSONL/OTLP 字段与 budget 事件不变 |
| **A4** | 拆 `rag/ingest.py`：loaders/chunking/indexes/application；MySQL/Chroma 适配器 | ✅ 已完成：`rag/{models,loaders,chunking,indexes,knowledge}.py`；MySQL ngram/Chroma 移到 `adapters/knowledge/`；旧 `rag/{ingest,mysql_store}.py` shim；RAG 测试全绿 |
| **A5** | MCP 拆 protocol/transport/handler/bridge | ✅ 已完成：`protocol/mcp_framing.py`、`adapters/mcp/{client,knowledge_server}.py`、`application/mcp_tools.py`、`ports/mcp_transport.py`；旧 `mcp/{framing,client,server}.py` shim；MCP/安全测试全绿 |
| **A6** | 架构测试 + 目标架构图 + 文档回填 | ✅ 已完成：`tests/test_architecture.py` 分层断言；`architecture.mmd`/PNG 改为 ports & adapters 分层图；**外围分层完成，核心 Agent 拆分在 A7.2** |
| **A7.1** | `Agent` 接收 `LLMClient`；composition/eval 注入 adapter；内部不再 import shim | ✅ 已完成：`OpenAICompatibleClient` 注入；`tests/test_agent_llm_port.py`；架构断言 `runtime/agent.py` 不 import shim/adapters |
| **A7.2** | 拆 Agent：上下文策略 + 工具执行 + 观察格式化；Agent <200 行 | ✅ 已完成：`domain/context_policy.py`、`application/{context,tool_executor,run_turn}.py`；`runtime/agent.py` **184 行**（facade）；190 tests 绿 |
| **A7.3** | EventSink/KnowledgeStore 取舍；架构断言扩展到 application/runtime | ✅ 已完成：**不新增 EventSink Protocol**（on_event callback + `observability/events.py` 函数式 sink 已是单一实现，加 Protocol 是空接口）；**不新增 KnowledgeStore port**（`rag/knowledge.py` 是应用 facade，MySQL/Chroma 已是 adapters，单消费者不值得抽象）；断言扩展到 ports/adapters/observability |
| **A7.4** | 文档/架构图回填；v0.3.0 发布；shim 删除计划 | 待做 |

原则：

1. **先加测试/边界断言，再搬代码**；
2. 每一步只移动职责，不改行为；`make check` 测试数不下降；
3. 旧 import 可用 shim 保留一个版本，下个版本删除；
4. 大文件拆分优先抽「纯函数/协议/适配器」，不重写 ReAct 语义；
5. 不做「一次性目录大搬家」PR。

## 非目标

- 不引入 Spring/Cordis 式 DI 容器；
- 不改成 async/await 重写（CLI 目前同步足够）；
- 不做多租户/Web/队列平台；
- 不为每个类造接口，只对 LLM、存储、知识库、工具、事件、MCP transport 六个真实边界抽象；
- 不为了目录好看牺牲可运行性。

## 风险与缓解

| 风险 | 缓解 |
|---|---|
| 搬文件破坏 import | 先加 shim/兼容导出；每步 `make check`；小 PR |
| 行为漂移 | 每步前后测试数、输出、JSONL 字段、CLI 退出码对比 |
| 过度抽象 | 只抽六个边界；domain 不引入框架类型 |
| 与 D4/安全改动冲突 | 基于最新 main；D4 已完成，A2 只搬不改；安全代码先测试再搬 |
| 重构拖慢生产门禁 | A0 只写文档；A1+ 与 G-30/G-32 等门禁交错，不阻塞 P0 |

## 后果

- 正面：领域可单测；存储/LLM/MCP 可替换；组合根可审计；新增能力不再往 `__main__.py`/`agent.py` 堆。
- 负面：短期目录变动多；需要维护兼容 shim；A1–A6 约 4–6 人日。
- 不改变：CLI 行为、数据 schema、现有安全边界、D4 行锁语义。

## 关联

- ADR-001：MySQL 主存储
- ADR-002：跨进程会话写一致性（D4）
- `docs/production-problems.md`：真实生产问题 → 设计 → 证据
- `docs/production-standard.md`：六门禁与项目级阈值
