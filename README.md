# AgentKernel

> 用 Python 从零实现的 **Agent 内核 + 知识库 MCP 工具**。不依赖 LangChain / Claude SDK 等任何 Agent 框架，证明「原理级」工程能力。

**一句话**：实习我用 Claude Agent SDK「会用」搭平台，这个项目反过来「会造」——从零写一个 Agent 内核。

---

## 是什么

一个可交互的 **CLI Agent**，能力：

- 多轮对话，上下文不丢（第 10 轮还记得第 1 轮要求）
- 能调用工具：内置工具 + 外部 MCP 工具
- 模型输出的非法 JSON 自动修复 / 降级，不崩溃
- 自带知识库，问答**带来源引用**

---

## 特性

| 特性 | 说明 |
|------|------|
| ReAct 主循环 | 思考 → 行动 → 观察 → 回复，带上下文管理 |
| 工具注册 | JSON Schema 参数校验、错误处理 |
| 非法 JSON 修复 | 三层：正则提取 → JSON 修复 → 降级纯文本 |
| SQLite 记忆 | 对话持久化、会话管理，重启不丢 |
| 知识库 RAG | PDF/MD/TXT → 分块（带重叠）→ 向量化 → 检索 |
| MCP 两端 | server 用官方 SDK，client 自实现 |

---

## 技术栈

| 组件 | 选型 | 说明 |
|------|------|------|
| 语言 | Python 3.11+ | — |
| 模型 | DeepSeek API | OpenAI 兼容接口 |
| 向量库 | ChromaDB | 本地持久化 |
| Embedding | BAAI/bge-small-zh-v1.5 | 中文向量 |
| 文档解析 | PyMuPDF + markdown-it-py | PDF / Markdown |
| 记忆 | SQLite（标准库 `sqlite3`） | 无外部依赖 |
| MCP server | `mcp` Python SDK | 官方实现 |
| MCP client | 自实现 | `tools/list` + `tools/call` |

---

## 架构

```
┌──────────────┐
│   CLI 用户    │
└──────┬───────┘
       │ 输入 / 输出
┌──────▼─────────────────────────────────────┐
│                  agent.py                   │  ← ReAct 主循环
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
                └── mcp_client.py ──▶ mcp_server/kb_server.py ──▶ rag/ingest.py ──▶ ChromaDB
```

| 模块 | 职责 |
|------|------|
| `agent.py` | ReAct 主循环 + 上下文管理 |
| `llm.py` | DeepSeek 调用封装（OpenAI 兼容） |
| `tools/registry.py` | 工具注册、JSON Schema 校验、错误处理 |
| `tools/json_repair.py` | 非法 JSON 三层修复 |
| `memory/sqlite_store.py` | 对话历史持久化、会话管理 |
| `rag/ingest.py` | 文档解析 → 分块 → 向量化入库 |
| `mcp_server/kb_server.py` | 知识库 MCP server（2 个 tool） |
| `mcp_client.py` | 自实现 MCP client，注册进内核 |

详细见 [docs/technical-scope-and-boundary.md](docs/technical-scope-and-boundary.md)。

---

## 快速开始（开发中）

> 项目进行中，以下为最终目标用法。

```bash
# 1. 装依赖
pip install openai chromadb sentence-transformers pymupdf markdown-it-py mcp python-dotenv

# 2. 配环境变量（.env，勿提交）
cp .env.example .env   # 填 DEEPSEEK_API_KEY=sk-xxx

# 3. 跑 CLI
python -m agentkernel
```

---

## 目录结构

```
AgentKernel/
├── README.md
├── docs/
│   ├── README.md                       # 里程碑文档索引
│   ├── project-background.md           # 项目背景说明
│   ├── technical-scope-and-boundary.md # 技术选型与边界
│   ├── milestone-1-kernel.md           # 里程碑 1：ReAct 内核可跑
│   ├── milestone-2-mcp.md              # 里程碑 2：知识库 MCP 打通
│   └── milestone-3-deliverables.md     # 里程碑 3：交付物与缓冲
├── pyproject.toml                 # 工程配置（依赖 + ruff + mypy + pytest）
├── src/agentkernel/               # 源码（src 布局）
│   ├── __main__.py                # CLI 入口
│   ├── runtime/                   # ReAct 循环 + 模型调用（借鉴 workbench runtime/）
│   ├── tools/                     # registry + contracts + json_repair（借鉴 OpenClaw）
│   ├── memory/                    # SQLite 记忆
│   ├── rag/                       # 文档入库
│   ├── mcp/                       # server（官方 SDK）+ client（自实现）
│   └── utils/                     # env + errors（借鉴 workbench utils/）
└── tests/                         # 测试（借鉴 workbench tests/）
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
5. README + 架构图 + 2 分钟演示录屏齐
6. 简历 bullet + 面试话术定稿

---

## 参考资料

- OpenClaw `tool-call-repair` 源码（JSON 修复的分层设计参考）
- agent-study Ch3（ReAct）、Ch10（MCP）、Ch11（Tool Calling）
- MCP 协议官方规范

---

## License

MIT
