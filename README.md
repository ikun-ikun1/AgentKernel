# AgentKernel

> 用 Python 从零实现的 **Agent 内核 + 知识库 MCP 工具**。不依赖 LangChain / Claude SDK 等任何 Agent 框架，证明「原理级」工程能力。

**一句话**：实习我用 Claude Agent SDK「会用」搭平台（AI Agent Workbench），这个项目反过来「会造」——从零写一个 Agent 内核。两个项目互补：一个是**用框架搭平台**，一个是**不套框架造内核**。

---

## 与实习项目互补

| 维度 | AI Agent Workbench（实习） | AgentKernel（个人项目） |
|------|---------------------------|------------------------|
| 核心问题 | 怎么用 Claude Agent SDK 快速搭一个团队工作台 | Agent 主循环 / 工具调用 / 上下文管理底层怎么实现 |
| 主循环 | SDK 内置，配置化调用 | 手写 ReAct：思考 → 行动 → 观察 → 回复 |
| 工具接入 | SDK tool_use + MCP server | 手写注册表 + JSON Schema 校验 + 自实现 MCP client |
| 失败处理 | 依赖框架 | 坏 JSON 三层修复 + 工具错误回灌 + 允许清单过滤 |
| 上下文 | 框架管理 | 自己实现 truncate 截断 + compact 压缩 |
| 记忆 | 数据库存业务数据 | SQLite 存对话历史，重启不丢 |
| 回答定位 | 平台化：Web + 审批 + 审计 | 内核化：CLI + 知识库带来源 + 可解释 |

面试主线：**「会用 → 会造」**——实习证明我能用框架交付业务，个人项目证明我能讲清框架底层每个环节。

---

## 是什么

一个可交互的 **CLI Agent**，能力：

- 多轮对话，上下文不丢（第 10 轮还记得第 1 轮要求）
- 能调用工具：内置工具 + 外部 MCP 工具
- 模型输出的非法 JSON 自动修复 / 降级，不崩溃
- 自带知识库，问答**带来源引用**
- SQLite 记忆，重启后历史仍在

---

## 特性

| 特性 | 说明 |
|------|------|
| ReAct 主循环 | 思考 → 行动 → 观察 → 回复，`MAX_STEPS` 防死循环 |
| 上下文管理 | truncate 固定首条用户要求；compact 调模型摘要压缩（失败降级截断） |
| 工具注册 | 纯 Python JSON Schema 校验（不引 jsonschema 依赖） |
| 非法 JSON 修复 | 三层：提取 → 修复 → 降级；借鉴 OpenClaw 的 **工具名允许清单 + payload 上限** |
| SQLite 记忆 | 会话 + 消息 + **工具调用审计** 持久化，重启不丢（标准库 `sqlite3`） |
| 知识库 RAG | PDF/MD/TXT → 分块（带重叠）→ 检索；ChromaDB 优先，**纯 Python 降级索引**兜底 |
| MCP 两端 | server 用官方 SDK（可选）+ 纯 Python stdio 入口；client 自实现 `Content-Length` 帧 + JSON-RPC 2.0 |
| LLM 调用 | OpenAI client 复用 + 超时/重试，失败统一 `LLMError` |
| 安全边界 | 计算器 AST 白名单、知识库只读、API Key 走 `.env` |

---

## 技术栈

| 组件 | 选型 | 说明 |
|------|------|------|
| 语言 | Python 3.11+ | — |
| 模型 | DeepSeek API | OpenAI 兼容接口 |
| 向量库 | ChromaDB（可选） | 未安装时降级为字符 2-gram 索引 |
| Embedding | BAAI/bge-small-zh-v1.5（可选） | 中文向量 |
| 文档解析 | PyMuPDF（可选） | PDF；MD/TXT 直接按 UTF-8 文本读取 |
| 记忆 | SQLite（标准库 `sqlite3`） | 无外部依赖 |
| MCP server | `mcp` Python SDK（可选） | 官方实现，未安装时进程内适配 |
| MCP client | 自实现 | `initialize` → `tools/list` → `tools/call` |

> 依赖最小化原则：核心闭环只依赖 `openai` + `python-dotenv`；RAG/MCP 重依赖全部可选，缺了也能演示。

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
│DeepSeek│  │ registry  │  │ sqlite_store   │
└───────┘  └────┬─────┘  └────────────────┘
                │ 注册工具
                ├── 内置工具（当前时间 / 计算器）
                └── mcp/client.py ──▶ mcp/server.py ──▶ rag/ingest.py ──▶ 知识库
```

| 模块 | 职责 |
|------|------|
| `runtime/agent.py` | ReAct 主循环 + 上下文管理（truncate/compact） |
| `runtime/llm.py` | DeepSeek 调用封装（OpenAI 兼容） |
| `tools/contracts.py` | 工具调用协议契约（允许清单 + 结构分类） |
| `tools/registry.py` | 工具注册、纯 Python JSON Schema 校验、错误处理 |
| `tools/json_repair.py` | 非法 JSON 三层修复（提取 → 修复 → 降级） |
| `memory/sqlite_store.py` | 会话 + 消息 + 工具调用审计（tool_logs）持久化 |
| `rag/ingest.py` | 文档解析 → 分块 → 向量化入库 → 检索（带来源） |
| `mcp/framing.py` | MCP stdio 帧协议（Content-Length + JSON-RPC） |
| `mcp/server.py` | 知识库 MCP server（官方 SDK 可选 + 纯 Python stdio 入口，2 个 tool） |
| `mcp/client.py` | 自实现 MCP client（stdio 子进程 / 进程内适配），注册进内核 |

详细见 [docs/technical-scope-and-boundary.md](docs/technical-scope-and-boundary.md)。

---

## 快速开始

```bash
# 1. 装核心依赖
pip install openai python-dotenv

# 可选：知识库 + MCP server（不装也能演示，自动降级）
pip install chromadb sentence-transformers pymupdf mcp

# 2. 配环境变量（.env，勿提交）
cp .env.example .env   # 填 DEEPSEEK_API_KEY=sk-xxx

# 3. 跑 CLI
python -m agentkernel --docs <文档路径>   # 可选：启动时入库文档

# 4. 跑评估（mock 模式无需 API Key，验证内核逻辑）
python eval.py

# 5. 单独启动 MCP stdio server（供自实现 client 或第三方 Host 调用）
python -m agentkernel.mcp.server <文档路径>
```

CLI 内置命令：`/new [标题]` 新建会话、`/sessions` 列出会话、`/history` 查看历史、`/ingest <路径>` 入库文档、`/docs` 列出文档、`/logs` 查看工具调用审计、`/help` 帮助、`/quit` 退出。

---

## 目录结构

```
AgentKernel/
├── README.md
├── eval.py                          # 5 用例评估脚本（mock / live）
├── docs/
│   ├── README.md                    # 里程碑文档索引
│   ├── project-background.md        # 项目背景说明（会用 → 会造）
│   ├── technical-scope-and-boundary.md
│   ├── learning-map.md              # 教学映射：agent-study ↔ OpenClaw ↔ Workbench
│   ├── milestone-1-kernel.md
│   ├── milestone-2-mcp.md
│   └── milestone-3-deliverables.md
├── pyproject.toml                   # 工程配置（依赖 + ruff + mypy + pytest）
├── src/agentkernel/                 # 源码（src 布局）
│   ├── __main__.py                  # CLI 入口（含 /ingest /docs /logs）
│   ├── runtime/                     # ReAct 循环 + 模型调用
│   ├── tools/                       # registry + contracts + json_repair
│   ├── memory/                      # SQLite 记忆（sessions/messages/tool_logs）
│   ├── rag/                         # 文档入库与检索
│   ├── mcp/                         # framing + server + client
│   └── utils/                       # env + errors
└── tests/                           # 46 个测试用例
```

---

## 里程碑

| 阶段 | 时间 | 验收 |
|------|------|------|
| [里程碑 1：ReAct 内核可跑](docs/milestone-1-kernel.md) | 8/29-9/08 | CLI 多轮 + 2 内置工具 + 坏 JSON 不崩 |
| [里程碑 2：知识库 MCP 打通](docs/milestone-2-mcp.md) | 9/09-9/18 | 问「XX 是什么」→ 检索回答带来源 |
| [里程碑 3：交付物与缓冲](docs/milestone-3-deliverables.md) | 9/19-9/25 | README + 架构图 + 录屏 + 简历可用 |

优先级分层：🔴 底线 > 🟡 重要 > 🟢 可砍。

---

## 验收标准（项目完成的定义）

1. CLI 多轮对话，上下文不丢（第 10 轮还记得第 1 轮要求）
2. 能调用 ≥2 个内置工具 + 1 个 MCP 知识库工具
3. 故意给非法 JSON，能修复或降级为纯文本，不崩溃
4. 知识库问答带来源引用
5. `python eval.py` 5 用例全过
6. README + 架构图 + 2 分钟演示录屏齐
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
