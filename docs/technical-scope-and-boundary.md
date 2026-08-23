# 技术选型与边界说明

## 1. 推荐技术选型

以下技术栈是本项目默认方案，目的是降低上手成本、减少工程变量，保证 4 周内完成可演示闭环。

| 组件 | 选型 | 选型理由 |
|------|------|---------|
| 语言 | Python 3.11+ | 已有 Python 和 Agent 项目经验 |
| 模型 | DeepSeek API（OpenAI 兼容） | 便宜、接口标准，换模型只改 base_url |
| 向量库 | ChromaDB | 本地、轻量、Python 原生，个人项目够用 |
| Embedding | BAAI/bge-small-zh-v1.5 | 中文效果好、体积小、本地可跑 |
| 文档解析 | PyMuPDF（PDF）；MD/TXT 按 UTF-8 文本读取 | 简单可靠，不引入无收益依赖 |
| 记忆 | SQLite（标准库 `sqlite3`） | 零部署，CLI 场景够用 |
| MCP server | `mcp` Python SDK | 官方实现，server 端不重复造轮子 |
| MCP client | 自实现 | 证明懂协议底层（`initialize` → `tools/list` → `tools/call`） |

技术选型写死，不中途换栈。若确实要换，需说明理由 + 对进度的影响，先确认再改。

## 2. 系统模块边界

MVP 阶段实现以下核心模块（借鉴 workbench 分层 + OpenClaw 设计）：

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
│llm.py     │ │ registry   │ │ sqlite_store   │
│DeepSeek   │ └────┬──────┘ └────────────────┘
└───────────┘     │ 注册工具
                  ├── 内置工具（当前时间 / 计算器）
                  └── mcp/client.py ──▶ mcp/server.py ──▶ rag/ingest.py ──▶ ChromaDB
```

| 模块 | 职责 |
|------|------|
| `runtime/agent.py` | ReAct 主循环 + 上下文管理（truncate/compact，编排核心） |
| `runtime/llm.py` | DeepSeek 调用封装，统一 `chat(messages) -> str` |
| `tools/contracts.py` | 工具调用协议契约（结构定义 + 工具名允许清单） |
| `tools/registry.py` | 工具注册、纯 Python JSON Schema 校验、错误处理 |
| `tools/json_repair.py` | 非法 JSON 三层修复（提取 → 修复 → 降级 + payload 上限） |
| `memory/sqlite_store.py` | 会话 + 消息 + 工具调用审计（tool_logs）持久化 |
| `rag/ingest.py` | 文档解析 → 分块 → 向量化入库；ChromaDB 优先 + 纯 Python 降级索引 |
| `mcp/framing.py` | MCP stdio 帧协议（Content-Length + JSON-RPC 2.0） |
| `mcp/server.py` | 知识库 MCP server（官方 SDK 可选 + 纯 Python stdio 入口，2 个 tool） |
| `mcp/client.py` | 自实现 MCP client（stdio 子进程 / 进程内适配），注册进内核 |
| `utils/env.py` / `utils/errors.py` | 环境变量 / 统一错误 |

> **借鉴来源**：
> - 分层（`runtime/` / `tools/` / `memory/` / `utils/` / `tests/`）：借鉴 AI Agent Workbench 的 `backend/` 结构
> - 工具调用契约（`tools/contracts.py`）：借鉴 OpenClaw tool-call-repair 的 `contracts.ts`
> - JSON 修复分层（提取 → 修复 → 降级）：借鉴 OpenClaw tool-call-repair 的 grammar/payload/promote/stream-normalizer 分层思想
> - 工具名允许清单 + payload 字节上限：借鉴 OpenClaw `scanPlainTextToolCall` 的 `matcher` 与 `maxPayloadBytes`
> - `src/` 布局 + `pyproject.toml` + ruff/mypy/pytest：标准 Python 工程配置

## 3. 工具调用协议边界

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

## 4. 安全边界

个人项目没有「企业安全」那么重，但以下底线不放松：

1. API Key 放 `.env`，用 python-dotenv 读，**不硬编码、不入库**（`.gitignore` 排除 `.env`）。
2. 不把通用 shell 暴露给模型；内置工具是固定实现，模型只能传参数。
3. 工具执行异常捕获后作为「观察」回灌，不让异常穿透崩溃。
4. 知识库检索只读（查询 + 列出），不提供写/删能力给模型。

## 5. 功能范围

### MVP 必达能力

1. CLI 多轮对话，上下文不丢。
2. 至少 2 个内置工具（当前时间 / 计算器）可被调用。
3. 非法 JSON 能修复或降级，不崩溃。
4. SQLite 记忆，重启后历史仍在。
5. 至少 1 个 MCP 知识库工具（`knowledge_query`）能带来源回答。
6. 有评估脚本验证核心用例。

### 可降级实现

1. 上下文压缩（compact）可以先用纯截断（truncate）替代。
2. FastAPI 演示层可选，CLI 够演示。
3. 2 分钟录屏可省。
4. RAG 只做朴素向量检索，不做混合检索/重排。

### 默认不做，除非单独确认

1. 不做 IM 渠道（飞书等）。
2. 不做 Agent 框架（LangChain / Claude SDK）。
3. 不做多租户、卡片交互。
4. 不做复杂 RAG 优化（混合检索/重排）。
5. 不做生产级部署。

## 6. 时间控制规则

个人项目，优先保证演示闭环。遇到以下情况立即收窄范围：

1. 单个功能连续投入超过 2 小时仍未跑通。
2. 需要研究大量框架内部实现。
3. 为了「更通用」而增加抽象层。

推荐处理方式：

1. 先跑通成功路径，再补错误处理。
2. 先写固定实现，再提取通用结构。
3. 先完成一个工具，再复制第二个工具。
4. 先本地演示，再考虑扩展。

## 7. 成功标准

项目成功不以功能数量判断，而以以下标准判断：

1. 能清楚解释为什么从零写、不套框架。
2. 能清楚解释 ReAct 循环和工具调用失败怎么处理。
3. 能清楚解释上下文太长为什么忘事、怎么截断/压缩。
4. 能演示「多轮 → 工具 → 知识库带来源 → 坏 JSON 不崩」闭环。
5. 能从原理、工程、面试三个角度讲清楚项目。
