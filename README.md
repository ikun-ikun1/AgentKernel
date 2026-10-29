# AgentKernel

> 一个用于研究 Agent Runtime、Tool Calling 与 MCP 协议的 Python CLI 原型。不依赖 LangChain / Claude Agent SDK，重点是先复现实习项目中由框架封装的底层机制，再针对具体可靠性问题进行工程优化和验证。

**一句话**：实习项目 AI Agent Workbench 负责「直接使用 Claude Agent SDK 交付一个可控的团队工作台」；AgentKernel 负责「先复现其中被 SDK 隐藏的 Runtime、Tool Calling 和 MCP 机制，再围绕可靠性与可恢复性做改进实验」。前者证明应用交付能力，后者证明能学习原理并做工程创新。

## 研究主线

项目不以“实现一个能对话的 Agent”为终点，而采用“基线实现 → 发现问题 → 针对性优化 → 场景验证”的路线：

1. 参考 `agent-study` 复现 ReAct、工具注册、观察回灌和记忆等基础机制，建立可解释的 Runtime 基线。
2. 参考 OpenClaw 的成熟工程思路，针对模型输出不稳定问题增加分层 JSON 修复、工具名 allowlist、payload 上限和纯文本降级。
3. 针对文档重复入库、内容更新和向量依赖不可用问题，增加 checksum 增量索引、MySQL ngram 持久化基线、可选向量检索和失败回退。
4. 用 fake LLM、故障输入、文档变更和 MCP 子进程场景验证优化，而不是只验证成功路径。

这里的“创新”是面向具体问题的工程改进，不是重新发明 ReAct 或 MCP 协议。

## 优化前后对比

| 研究问题 | 基线做法 | 优化后 | 验证方式 |
|----------|----------|--------|----------|
| 模型输出非法 JSON，或长文本被误判成工具调用 | 直接 `json.loads`，失败即崩溃或误执行 | 平衡括号提取 → 格式修复 → 工具名 allowlist + payload 上限 → 失败降级纯文本 | 噪声 JSON、单引号、代码围栏、未知工具、超长载荷测试 |
| 上下文变长后早期约束丢失 | 全量携带历史或简单截断 | 保留首条用户要求；旧消息优先 compact 摘要，摘要失败再 truncate | 超预算历史、摘要失败、MAX_STEPS 测试 |
| 文档重复入库、修改后索引难维护 | 每次全量重建 | SHA-256 checksum 增量更新，稳定 `doc_id:ordinal` chunk ID，MySQL ngram 持久化基线 | 重复入库返回 0；修改后仅重建该文档 |
| 向量依赖不可用导致检索失败 | 只依赖向量或退化为内存索引 | 保留 MySQL ngram 持久化基线；`auto/hybrid` 降级并提示，`semantic` fail-fast | 无 chromadb/sentence-transformers 环境测试 |

当前验证结果：65 个默认测试用例通过，2 个 MySQL 集成测试因未配置 DSN 跳过；`python eval.py` mock 模式 5/5。MySQL 集成测试仍需在真实 MySQL 实例上单独验收。

---

## 与实习项目互补

| 维度 | AI Agent Workbench（实习） | AgentKernel（个人项目） |
|------|---------------------------|------------------------|
| 核心问题 | 如何用 Claude Agent SDK 交付团队工作台 | Agent Runtime 的关键机制如何实现和验证 |
| 主循环 | SDK 内置，重点是业务编排 | 手写 ReAct：思考 → 行动 → 观察 → 回复 |
| 工具接入 | 面向业务的 CLI/MCP Adapter、Agent 白名单 | 最小 Tool Registry、调用契约、参数校验 |
| 失败处理 | SDK/业务层错误处理、审批和审计 | 坏 JSON 修复、非法调用降级、工具错误回灌 |
| 上下文 | SDK session、跨会话记忆和 Web 会话 | truncate + compact 的策略实验 |
| 记忆 | 面向用户的会话、审批和审计数据 | MySQL 主存储；SQLite 仅作为测试适配器 |
| MCP / RAG | 业务工具接入与制度问答场景 | MCP wire protocol 实验；RAG 作为外部状态接入与引用追踪样例 |
| 交付形态 | 产品化：Web + 多 Agent + 审批 + 审计 | 教学型：CLI + 单元测试 + eval + 代码走读 |

面试主线：**「会用 → 会学习底层」**——实习证明我能直接使用框架交付业务，个人项目证明我能复现并验证框架隐藏的底层机制。

---

## 是什么

一个用于验证 Runtime 与协议机制的 **CLI Agent 研究原型**，能力：

- 多轮对话，上下文不丢（第 10 轮还记得第 1 轮要求）
- 能调用工具：内置工具 + 外部 MCP 工具
- 模型输出的非法 JSON 自动修复 / 降级，不崩溃
- 通过持久化检索模块完成带页码/来源的知识库问答
- 支持文档指纹、增量入库、删除、MySQL ngram 词法检索和可选向量混合检索，用于研究文档更新与引用追踪

这里不建设 Workbench 的业务知识库产品，检索模块只用于验证持久化索引、增量更新、结果追踪和外部工具接入。

---

## 特性

| 特性 | 说明 |
|------|------|
| ReAct 主循环 | 思考 → 行动 → 观察 → 回复，`MAX_STEPS` 防死循环；支持单工具与多工具（`actions`）调用 |
| 上下文管理 | truncate 固定首条用户要求；compact 调模型摘要压缩（失败降级截断） |
| 工具注册 | 纯 Python JSON Schema 校验（不引 jsonschema 依赖） |
| 非法 JSON 修复 | 三层：提取 → 修复 → 降级；借鉴 OpenClaw 的 **工具名允许清单 + payload 上限** |
| MySQL 记忆 | 会话 + 消息 + **工具调用审计** 持久化，重启不丢；SQLite 仅作为测试适配器 |
| 检索实验模块 | PDF/MD/TXT → 指纹与增量索引 → MySQL ngram 全文检索；可选 Embedding + Chroma 混合检索，结果保留页码与来源 |
| MCP 两端 | server 用官方 SDK（可选）+ 纯 Python stdio 入口；client 自实现 `Content-Length` 帧 + JSON-RPC 2.0，支持初始化协商与 `structuredContent` |
| LLM 调用 | OpenAI client 复用 + 超时/重试，失败统一 `LLMError` |
| 外部 MCP | CLI `--mcp-profile <name>` 接入 profile 声明的 stdio MCP server（精确 argv + env 白名单，工具名自动加前缀） |
| 安全边界 | 计算器 AST 白名单、知识库只读、API Key 走 `.env` |

## 边界声明

### AgentKernel 要证明什么

1. 模型本质上只返回文本，代码如何把文本解析为工具调用并安全执行。
2. ReAct 循环如何处理工具观察、失败重试和最大步数。
3. 上下文超限时 truncate / compact 如何工作，以及失败如何降级。
4. MCP 的 `initialize`、`tools/list`、`tools/call` 和 stdio 帧协议如何实现。
5. 在不依赖 Agent 框架的情况下，如何用测试和评估脚本验证上述行为。

### AgentKernel 明确不负责什么

1. 不重复实现 AI Agent Workbench 的 Web、SSE、Agent manifest 和业务路由。
2. 不实现 Workbench 的人工审批、跨会话产品记忆、企业鉴权和完整审计平台。
3. 不建设 Workbench 的业务知识库产品、文档管理 UI 或企业知识权限平台；`rag/` 只提供研究和演示所需的检索模块。
4. 不接入真实企业系统，不提供 shell、插件市场、多租户或生产部署能力。
5. 不追求替代 Claude Agent SDK、LangGraph 或 OpenClaw，而是用于解释它们解决的问题。

### 两个项目的组合叙事

```text
AI Agent Workbench: 业务应用层
  Web / Agent 配置 / CLI 与 MCP 工具 / 审批 / 审计 / 会话产品体验
                                |
                                | 对照：框架提供了什么能力
                                v
AgentKernel: Runtime 学习与协议层
  ReAct Loop / Tool Contract / JSON Repair / Context Policy / MCP Wire Protocol
```

---

## 技术栈

| 组件 | 选型 | 说明 |
|------|------|------|
| 语言 | Python 3.11+ | — |
| 模型 | DeepSeek API | OpenAI 兼容接口 |
| 检索 | MySQL ngram + 可选 Chroma 混合检索 | 对比词法/语义召回，并验证增量索引与来源保留 |
| 文档解析 | PyMuPDF（可选）+ 标准库 | PDF 保留页码；MD/TXT 直接读取 |
| 记忆 | MySQL 8；SQLite 测试适配器 | 连接池、事务、索引和迁移贴近服务端场景 |
| MCP server | `mcp` Python SDK（可选） | 官方实现，未安装时进程内适配 |
| MCP client | 自实现 | `initialize` → `tools/list` → `tools/call` |

> 依赖分层：生产运行模式使用 MySQL 持久化，SQLite 仅作为测试和本地开发适配器；检索实验使用 `.[rag]`，MCP 官方 server 使用 `.[mcp]`。缺少向量依赖时回退到 MySQL ngram，不丢失文档事实数据。

---

## 架构

```
┌──────────────┐
│   CLI 用户    │
└──────┬───────┘
       │ 输入 / 输出
┌──────▼─────────────────────────────────────┐
│              runtime/agent.py               │  ← ReAct 主循环
│    思考 → 行动 → 观察 → 回复                 │
│    上下文管理：truncate 截断 + compact 压缩   │
└──┬────────────┬────────────┬────────────────┘
   │            │            │
┌──▼────┐  ┌────▼─────┐  ┌───▼────────────┐
│ llm.py │  │ tools/    │  │ memory/        │
│DeepSeek│  │ registry  │  │ MySQL Store    │
└───────┘  └────┬─────┘  └────────────────┘
                │ 注册工具
                ├── 内置工具（当前时间 / 计算器）
                └── mcp/client.py ──▶ mcp/server.py ──▶ rag/ingest.py
                                               ├── MySQL 文档目录 + ngram
                                              └── Chroma（可选向量）
```

| 模块 | 职责 |
|------|------|
| `runtime/agent.py` | ReAct 主循环 + 上下文管理（truncate/compact） |
| `runtime/llm.py` | DeepSeek 调用封装（OpenAI 兼容） |
| `tools/contracts.py` | 工具调用协议契约（允许清单 + 结构分类） |
| `tools/registry.py` | 工具注册、纯 Python JSON Schema 校验、错误处理 |
| `tools/json_repair.py` | 非法 JSON 三层修复（提取 → 修复 → 降级） |
| `memory/` | MySQL 主存储与 SQLite 测试适配器：会话、消息和工具调用审计 |
| `rag/ingest.py` | 文档解析、指纹增量入库、MySQL ngram、可选向量索引、混合召回和来源元数据 |
| `mcp/framing.py` | MCP stdio 帧协议（Content-Length + JSON-RPC） |
| `mcp/server.py` | 知识库 MCP server（官方 SDK 可选 + 纯 Python stdio 入口，2 个 tool） |
| `mcp/client.py` | 自实现 MCP client（stdio 子进程 / 进程内适配），注册进内核 |

详细见 [docs/technical-scope-and-boundary.md](docs/technical-scope-and-boundary.md)。

---

## 快速开始

```bash
# 1. 装核心依赖 + MySQL 主存储依赖
pip install openai python-dotenv "sqlalchemy>=2.0" "pymysql>=1.1" "alembic>=1.13"

# 检索实验（PDF + 可选向量混合检索）
pip install -e ".[rag]"

# 可选：官方 MCP server SDK
pip install mcp

# 2. 启动 MySQL 8（ADR-001 主存储）
docker compose up -d mysql
# 或使用本地已有 MySQL：在 .env 中设置 AGENTKERNEL_DB_URL / AGENTKERNEL_KB_DSN

# 3. 配环境变量（.env，勿提交）
cp .env.example .env   # 填 DEEPSEEK_API_KEY=sk-xxx，并按需调整 MySQL DSN

# 4. 跑 CLI（默认 MySQL；本地无 MySQL 可用 --db sqlite:///:memory: --kb-db :memory:）
python -m agentkernel --kb-backend hybrid --docs <文档路径>

# 4. 跑评估（mock 模式无需 API Key，验证内核逻辑）
python eval.py

# 5. 单独启动 MCP stdio server（供自实现 client 或第三方 Host 调用）
python -m agentkernel.mcp.server <文档路径>

# 6. 接入外部 stdio MCP server（P0-5：只接受 profile 声明的命令与精确 argv）
#    复制 mcp_profiles.example.toml 为 mcp_profiles.toml，按需修改 command/args，然后：
python -m agentkernel --mcp-profile kb-server
#    文档入库默认只允许当前目录；需要别的目录时显式配置：
#    AGENTKERNEL_DOC_ROOTS=/data/docs:/home/me/notes python -m agentkernel --docs /data/docs
```

CLI 内置命令：`/new [标题]` 新建会话、`/sessions` 列出会话、`/history` 查看历史、`/ingest <路径>` 增量入库 PDF/MD/TXT、`/docs` 列出文档、`/logs` 查看工具调用审计、`/help` 帮助、`/quit` 退出。未安装向量依赖时仍使用持久化 MySQL ngram，不会退化为内存索引。

---

## 目录结构

```
AgentKernel/
├── README.md
├── eval.py                          # 5 用例评估脚本（mock / live）
├── docs/
│   ├── README.md                    # 里程碑文档索引
│   ├── project-background.md        # 项目背景说明（会用 → 会学习底层）
│   ├── technical-scope-and-boundary.md
│   ├── learning-map.md              # 教学映射：agent-study ↔ OpenClaw ↔ Workbench
│   ├── milestone-1-kernel.md
│   ├── milestone-2-mcp.md
│   ├── milestone-3-deliverables.md
│   ├── architecture.mmd / architecture.png
│   ├── demo-script.md
│   └── resume-and-interview.md
├── pyproject.toml                   # 工程配置（依赖 + ruff + mypy + pytest）
├── src/agentkernel/                 # 源码（src 布局）
│   ├── __main__.py                  # CLI 入口（含 /ingest /docs /logs）
│   ├── runtime/                     # ReAct 循环 + 模型调用
│   ├── tools/                       # registry + contracts + json_repair
│   ├── memory/                      # MySQL Store + SQLite 测试适配器
│   ├── rag/                         # 文档入库与检索
│   ├── mcp/                         # framing + server + client
│   └── utils/                       # env + errors
└── tests/                           # 65 个默认测试用例（另有 2 个 MySQL 集成测试按需启用）
```

---

## 里程碑

| 阶段 | 时间 | 验收 |
|------|------|------|
| [里程碑 1：ReAct 内核可跑](docs/milestone-1-kernel.md) | 8/29-9/08 | CLI 多轮 + 2 内置工具 + 坏 JSON 不崩 |
| [里程碑 2：MCP 协议与示例工具链打通](docs/milestone-2-mcp.md) | 9/09-9/18 | MCP 协议链路可测，示例工具返回带来源结果 |
| [里程碑 3：交付物与缓冲](docs/milestone-3-deliverables.md) | 9/19-9/25 | README + 架构图 + 录屏 + 简历可用 |

优先级分层：🔴 底线 > 🟡 重要 > 🟢 可砍。

---

## 验收标准（项目完成的定义）

1. CLI 多轮对话，上下文不丢（第 10 轮还记得第 1 轮要求）
2. 能调用 ≥2 个内置工具 + 1 个 MCP 知识库工具
3. 故意给非法 JSON，能修复或降级为纯文本，不崩溃
4. 知识库问答带来源引用
5. `python eval.py` 5 用例全过
6. README + 架构图 + 演示脚本齐（录屏可选）
7. 简历 bullet + 面试话术定稿

---

## 参考资料

- OpenClaw `packages/tool-call-repair` 源码（grammar/payload/promote 分层设计）
- AI Agent Workbench 后端分层（`runtime/` / `utils/` / `tests/`）
- agent-study Ch3（ReAct）、Ch10（MCP）、Ch11（Tool Calling）
- MCP 协议官方规范

---

## License

MIT
