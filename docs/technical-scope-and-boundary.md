# 技术选型与边界说明

## 1. 推荐技术选型

以下技术栈分为 Runtime 核心、MySQL 持久化层和检索实验模块三层。项目不做 Workbench 的业务 UI 和企业治理；检索模块用于验证持久化、增量更新、召回和来源保留，不定位为生产知识库。

| 组件 | 选型 | 选型理由 |
|------|------|---------|
| 语言 | Python 3.11+ | 已有 Python 和 Agent 项目经验 |
| 模型 | DeepSeek API（OpenAI 兼容） | 便宜、接口标准，换模型只改 base_url |
| 词法检索 | MySQL 8 InnoDB `FULLTEXT` + ngram | 主流数据库持久化、可索引，作为中文词法检索基线 |
| 语义检索 | ChromaDB + sentence-transformers（可选） | 用于对比语义召回；缺失时保留 MySQL ngram，便于实验继续进行 |
| 主存储 | MySQL 8 | 使用连接池、事务、索引和迁移机制，贴近实际服务端部署 |
| 测试存储 | SQLite（测试适配器） | 测试快速、零部署；不作为生产主存储 |
| 文档解析 | PyMuPDF（可选）+ 标准库 | PDF 保留页码，MD/TXT 直接读取 |
| MCP server | `mcp` Python SDK（可选）+ 纯 Python stdio 入口 | 对比官方 SDK 与最小协议实现 |
| MCP client | 自实现 | 验证协议底层（`initialize` → `tools/list` → `tools/call`） |

技术选型写死，不中途换栈。若确实要换，需说明理由 + 对进度的影响，先确认再改。

## 2. 与 AI Agent Workbench 的系统边界

两个项目的关系不是“两个 Agent 产品”，而是“应用层交付”和“底层机制研究”的互补：

| 层次 | AI Agent Workbench | AgentKernel |
|------|--------------------|-------------|
| 产品入口 | Web、SSE、Agent 选择、会话生命周期 | CLI，仅用于触发 Runtime |
| Agent Runtime | Claude Agent SDK 提供主循环、tool_use、session | 自己实现最小 ReAct 主循环 |
| 工具与权限 | 业务 CLI/MCP、manifest 白名单、人工审批 | 固定 Tool Registry、协议分类、Schema 子集校验；内置唯一副作用写工具走本地 y/N 审批；外部 MCP 工具统一审批 P1 |
| 业务能力 | 工时、考勤、制度问答、项目等业务 Agent | 时间、计算器和检索/MCP 实验样例 |
| 持久化与观测 | 用户会话、跨会话记忆、审批和审计产品 | MySQL 持久化 Runtime 状态；SQLite 仅用于测试适配 |
| MCP | 业务工具集成 | stdio/JSON-RPC 协议实验和互操作测试 |

### AgentKernel 的硬边界

AgentKernel 不实现以下 Workbench 能力：

1. Web 前端、SSE 流式 UI、登录和用户系统。
2. Agent manifest、业务子 Agent、路由器和 Skills 配置平台。
3. 企业审批平台、企业鉴权、跨 Agent 权限隔离和生产级审计平台；本地写工具的 y/N 审批除外。
4. 真实工时、考勤、制度或其他企业系统接入。
5. 文档管理 UI、企业知识权限平台、多租户和部署运维；RAG 的索引与检索核心仍属于本项目主线。

`rag/` 是用于实验的检索模块；`mcp/server.py` 是它的只读协议适配层。Workbench 可以参考这类实现，但不由 AgentKernel 实现业务知识库页面、组织权限和审批流程。

### 研究与优化主线

项目不把“能跑通一个 Agent”作为最终成果，而采用“基线实现 → 暴露问题 → 针对性改进 → 场景验证”的路线：

| 研究问题 | 基线做法 | 改进方案 | 验证方式 |
|----------|----------|----------|----------|
| 模型输出不是合法 JSON，或普通长文本被误识别为工具调用 | 直接解析模型输出 | 平衡结构提取、格式修复、工具名 allowlist、payload 上限，失败降级为文本 | 噪声 JSON、单引号、代码围栏、未知工具和超长载荷 |
| 对话历史变长后早期约束丢失 | 固定携带全部历史或仅做固定截断 | 保留首条用户要求；旧消息优先 compact，摘要失败再 truncate | 超预算历史、摘要失败和最大步数场景 |
| 文档重复入库、修改后索引难以维护，向量依赖可能不可用 | 每次重新构建或只依赖向量检索 | checksum 增量更新；MySQL ngram 作为持久化基线，向量检索可选并支持回退 | 重复入库、修改文档、向量依赖缺失 |

其中，工具调用可靠性和检索链路可恢复性是本项目的主要优化方向；MCP 协议帧、能力协商和外部 Server 接入属于互操作性验证，不宣称重新发明协议。

### 数据库决策

SQLite 适合实习项目早期快速验证，但无法充分体现服务端场景中的连接池、并发访问、事务边界、索引设计和数据库迁移。因此 AgentKernel 将 MySQL 8 设为主存储，SQLite 仅保留为测试适配器。

MySQL 负责会话、消息、工具日志、文档元数据和文档 Chunk；Chroma 只负责可选向量索引，MySQL 保存文档与 Chunk 的事实数据。中文词法检索使用 MySQL InnoDB `FULLTEXT` 的 ngram parser，向量检索不可用时仍可走 MySQL 词法基线。

数据库访问必须通过 Store/Repository 接口，Runtime 不直接依赖具体数据库驱动。这样既能在测试中使用 SQLite，也能在实际运行中使用 MySQL，而不会把数据库切换逻辑扩散到 Agent 主循环。

## 3. 系统模块边界

研究阶段实现以下核心模块。模块按“Runtime 基线 → 问题优化 → 场景验证”的链路组织，不复制 Workbench 的 Web/API/业务层：

```
┌──────────────┐
│   CLI 用户    │
└──────┬───────┘
       │ 输入 / 输出
┌──────▼─────────────────────────────────────┐
│            runtime/agent.py                 │  ← ReAct 主循环
│    思考 → 行动 → 观察 → 回复                 │
│    上下文管理：truncate 截断 + compact 压缩   │
└──┬────────────┬────────────┬────────────────┘
   │            │            │
┌──▼────────┐ ┌──▼────────┐ ┌───▼────────────┐
│runtime/   │ │ tools/     │ │ memory/        │
│llm.py     │ │ registry   │ │ store/repo     │
│DeepSeek   │ └────┬──────┘ └────────────────┘
└───────────┘     │ 注册工具
                  ├── 内置工具（当前时间 / 计算器）
                   └── mcp/client.py ──▶ mcp/server.py ──▶ rag/ingest.py
                                                      ├── MySQL FULLTEXT + ngram
                                                     └── Chroma（可选）
```

| 模块 | 职责 |
|------|------|
| `runtime/agent.py` | ReAct 主循环 + 上下文管理（truncate/compact，编排核心） |
| `adapters/llm/openai_compatible.py` | DeepSeek 调用封装，统一 `chat(messages) -> str` |
| `tools/contracts.py` | 工具调用协议契约（结构定义 + 工具名允许清单） |
| `tools/registry.py` | 工具注册、纯 Python JSON Schema 校验、错误处理 |
| `tools/json_repair.py` | 非法 JSON 三层修复（提取 → 修复 → 降级 + payload 上限） |
| `memory/` | Store/Repository 接口及 MySQL 主存储、SQLite 测试适配器 |
| `rag/ingest.py` | 文档指纹、增量入库、分块、来源元数据、MySQL ngram 与可选向量混合检索 |
| `mcp/framing.py` | MCP stdio 帧协议（Content-Length + JSON-RPC 2.0） |
| `mcp/server.py` | 只读示例 MCP server（官方 SDK 可选 + 纯 Python stdio 入口，2 个 tool） |
| `mcp/client.py` | 自实现 MCP client（stdio 子进程 / 进程内适配），注册进内核 |
| `utils/env.py` / `utils/errors.py` | 环境变量 / 统一错误 |

> **借鉴来源**：
> - 分层（`runtime/` / `tools/` / `memory/` / `utils/` / `tests/`）：借鉴 AI Agent Workbench 的工程组织方式，但不复制其 Web、业务和审批层
> - 工具调用契约（`tools/contracts.py`）：借鉴 OpenClaw tool-call-repair 的 `contracts.ts`
> - JSON 修复分层（提取 → 修复 → 降级）：借鉴 OpenClaw tool-call-repair 的 grammar/payload/promote/stream-normalizer 分层思想
> - 工具名允许清单 + payload 字节上限：借鉴 OpenClaw `scanPlainTextToolCall` 的 `matcher` 与 `maxPayloadBytes`
> - `src/` 布局 + `pyproject.toml` + ruff/mypy/pytest：标准 Python 工程配置
> - MySQL 8 + Alembic + Docker Compose：服务端持久化与本地可复现环境

## 4. 工具调用协议边界

模型被要求按固定 JSON 输出工具调用：

```json
{"action": "工具名", "action_input": {"参数": "值"}}
```

多工具调用：

```json
{"actions": [{"action": "工具名1", "action_input": {...}}, {"action": "工具名2", "action_input": {...}}]}
```

最终回答：

```json
{"action": "final_answer", "action_input": "回答内容"}
```

边界规则：

1. 工具必须通过 registry 注册，模型不能调用未注册的工具。
2. 模型输出先按协议契约分类；工具调用必须命中**名字允许清单**（单工具与多工具数组都查），未注册工具一律降级为纯文本。
3. 工具参数必须经 JSON Schema 校验（required / type / properties / enum / items / additionalProperties），非法参数返回明确错误。
4. 模型输出非法 JSON 走三层修复：正则提取 → JSON 修复 → 降级纯文本；单候选 payload 超过 256KB 直接放弃修复。
5. ReAct 循环设 MAX_STEPS 上限，防止死循环；多工具调用当前按顺序执行（教学版便于解释观察回灌顺序）。
6. 历史超预算时 truncate 固定首条用户要求；超过 compact 阈值时优先摘要压缩，压缩失败降级截断。

## 5. 安全边界

个人项目不承担 Workbench 的企业安全职责，但以下 Runtime 级底线不放松：

1. API Key 放 `.env`，用 python-dotenv 读，**不硬编码、不入库**（`.gitignore` 排除 `.env`）。
2. 不把通用 shell 暴露给模型；内置工具是固定实现，模型只能传参数。
3. 工具执行异常捕获后作为「观察」回灌，不让异常穿透崩溃。
4. 模型可见的知识库 MCP 工具只读（查询 + 列出）；写/删只保留在 CLI `/ingest` 与 `KnowledgeBase.delete_document` 运维入口，不暴露给模型。

## 5.1 当前安全防护与未实现边界

当前已实现的 Runtime 级防护包括：

1. SQL 使用参数绑定；计算器使用 AST 白名单，不使用 `eval`/`exec`。
2. 工具名称使用 allowlist，参数执行基础 JSON Schema 校验。
3. MCP 帧具备长度限制，stdio Client 具备读取超时。
4. Agent 具备最大步数，JSON payload 具备大小限制。
5. API Key 从环境变量读取，知识库 MCP 示例只暴露查询和列出操作。

以下能力当前未实现，面试时必须明确说明：

1. 文档和 MCP 返回内容属于不可信数据，尚未实现完整 Prompt Injection 防护和工具结果隔离。
2. 外部 `--mcp` 命令默认依赖用户信任，尚未实现命令白名单、环境变量隔离和操作系统沙箱。
3. 文档入库尚未完整限制允许根目录、文件数量、PDF 大小和递归深度。
4. 尚未实现用户认证、授权、工具风险分级、企业审批平台、多租户隔离和限流；本地写工具的 y/N 审批已实现。
5. 工具日志仅用于 Runtime 观察，尚未实现敏感字段脱敏、访问控制、加密和不可篡改审计。
6. 尚未实现完整资源保护，包括计算器数值规模、Schema 深度、动作数量和所有检索参数上限。

如果将 CLI 扩展为联网服务，优先补充：输入与资源限制、外部 MCP 沙箱、工具授权/审批、Prompt Injection 防护、日志脱敏和认证授权。当前项目不把这些企业治理能力伪装成已完成能力。

## 6. 具体实现范围

### 必须实现并可验证

1. `runtime/agent.py` 能执行最多 `MAX_STEPS` 的 ReAct 循环。
2. `tools/contracts.py` 能区分单工具、多工具和最终回答协议。
3. `tools/registry.py` 能注册工具、生成描述、校验参数并把异常转为观察结果。
4. `tools/json_repair.py` 能处理带噪声/代码围栏/尾逗号/单引号 JSON，失败时降级纯文本。
5. `ContextConfig` 能执行首条用户要求保留、最近消息截断和摘要压缩降级。
6. `mcp/framing.py`、`mcp/client.py`、`mcp/server.py` 能完成 `initialize → tools/list → tools/call`。
7. `eval.py` 和 `tests/` 能用 fake LLM 验证上述行为，不依赖真实 API。

### 检索实验能力

1. `memory/`：通过统一 Store/Repository 接口完成 MySQL 消息恢复和工具观察记录，SQLite 仅用于测试。
2. `rag/ingest.py`：文档 checksum、增量更新、稳定 chunk ID、MySQL ngram 全文检索和可选向量索引。
3. `rag/ingest.py`：保留 source/page/section 元数据，检索结果可生成可审计引用。
4. `mcp/server.py`：通过 `knowledge_query` / `knowledge_list` 暴露只读检索能力，验证 Runtime 接入外部状态的方式。
5. `__main__.py`：CLI 作为运维/开发入口，支持持久化知识库目录。

### 可降级实现

1. 上下文压缩（compact）可以先用纯截断（truncate）替代。
2. 向量依赖不可用时降级为 MySQL ngram 全文检索，不能降级为丢失数据的内存索引。
3. PDF 依赖不可用时只拒绝 PDF，不影响已有 MD/TXT 索引和查询。
4. MCP server 可使用纯 Python stdio 实现，不要求官方 SDK；官方 SDK 仅作为可选实现方式。
5. 2 分钟录屏可省，测试、评估和索引一致性验证优先。

### 默认不做，且不属于本项目主线

1. 不做 Web、SSE、Agent manifest、子 Agent 和业务路由。
2. 不做企业审批平台/审批卡片、企业鉴权、跨会话产品记忆和完整审计平台；本地写工具的 y/N 审批是唯一例外。
3. 不做 IM 渠道（飞书等）和真实企业系统接入。
4. 不做文档管理 UI、企业权限平台和多租户知识库；混合检索、增量索引和来源追踪仅属于本项目的实验范围。
5. 不做 Agent 插件市场、多租户和生产级部署。
6. 不引入 LangChain / Claude SDK 作为 Runtime 实现；它们只作为实习项目对照和文档讨论对象。

## 7. 时间控制规则

个人项目，优先保证端到端演示。遇到以下情况立即收窄范围：

1. 单个功能连续投入超过 2 小时仍未跑通。
2. 需要研究大量框架内部实现。
3. 为了「更通用」而增加抽象层。

推荐处理方式：

1. 先跑通成功路径，再补错误处理。
2. 先写固定实现，再提取通用结构。
3. 先完成一个工具，再复制第二个工具。
4. 先本地演示，再考虑扩展。

## 8. 成功标准

项目成功不以功能数量判断，而以以下标准判断：

1. 能清楚解释为什么参考 agent-study 复现、不套框架。
2. 能清楚解释 ReAct 循环和工具调用失败怎么处理。
3. 能清楚解释上下文太长为什么忘事、怎么截断/压缩。
4. 能用测试或 eval 证明「多轮 → 工具 → MCP → 坏 JSON 不崩」端到端覆盖。
5. 能说明检索实验与 Workbench 业务知识库的边界：前者用于验证机制，后者是业务应用。
6. 能从原理、工程、协议、数据一致性和面试五个角度讲清楚项目。
