# 技术文档：架构设计

> 本文档描述 AgentKernel 的总体架构、模块职责、一次对话的完整数据流，以及 ReAct 循环、工具调用、上下文管理、MCP 两端的关键设计。
> 配套：[design.md](design.md)（设计决策）、各阶段文档。

---

## 一、总体架构

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

**分层**：`agent.py` 是大脑（编排），`llm.py`/`tools/`/`memory/` 是它的手和记性，`mcp_*` 和 `rag/` 是外部能力。

---

## 二、模块职责

### 1. `agent.py` — ReAct 主循环（核心）

职责：编排「思考 → 行动 → 观察 → 回复」循环，直到得出最终答案。

伪代码：

```
def run(session_id, user_input):
    history = memory.load(session_id)          # 加载历史
    history.append(user_message(user_input))
    for step in range(MAX_STEPS):              # 防死循环，如 10 步
        context = build_context(history)       # 组装 + 截断/压缩
        raw = llm.chat(context)                # 模型输出
        parsed = parse_action(raw)             # 解析：工具调用 or 最终回答
        if parsed.is_final:
            history.append(assistant_message(parsed.answer))
            memory.save(history)
            return parsed.answer
        # 是工具调用
        tool = registry.get(parsed.action)     # 找工具
        result = tool.run(parsed.action_input) # 执行 → 观察
        history.append(tool_observation(result))
    return fallback("达到步数上限")
```

关键点：
- **MAX_STEPS 上限**：防止模型反复调工具死循环。
- **观察结果回灌**：每次工具执行结果都写回历史，让模型「看到」结果再决定下一步。
- **错误兜底**：工具执行报错时，把错误信息作为观察回灌，让模型重试。

### 2. `llm.py` — 模型调用封装

- 用 `openai` SDK，`base_url` 指向 DeepSeek（OpenAI 兼容）。
- 统一入口 `chat(messages) -> str`，屏蔽底层细节，方便换模型。
- API Key 从环境变量读（`DEEPSEEK_API_KEY`），不硬编码。

### 3. `tools/registry.py` — 工具注册

- 每个工具声明：名称、描述、参数 JSON Schema。
- 注册表负责：登记工具 → 生成给模型的工具描述 → 校验参数 → 执行 → 捕获异常。
- 参数校验：用 JSON Schema 验证模型传的参数，非法则返回明确错误（而不是崩）。

### 4. `tools/json_repair.py` — 非法 JSON 修复

模型输出的工具调用不一定是合法 JSON，三层修复（详见 [design.md](design.md)）：

1. **正则提取**：从文本里抠出 `{...}` 片段
2. **JSON 修复**：补括号、去尾注、处理引号/逗号等常见错误
3. **降级纯文本**：三次都失败 → 把原始输出当普通回复，不崩

### 5. `memory/sqlite_store.py` — 对话记忆

- 用 SQLite 存会话和消息，重启不丢。
- Schema 设计见下文「上下文管理」。

### 6. `rag/ingest.py` — 文档入库

- 解析：PyMuPDF（PDF）、markdown-it-py（MD）、纯文本（TXT）
- 分块：按标题/段落切块，**块间带重叠**（避免信息截断）
- 向量化：bge-small-zh-v1.5 → 存入 ChromaDB

### 7. `mcp_server/kb_server.py` — 知识库 MCP server

- 用官方 `mcp` SDK，暴露 2 个工具：
  - `knowledge_query(query, top_k)`：向量检索，返回带来源的片段
  - `knowledge_list()`：列出已入库文档
- 这是「server 端」——参考实习 M3 的 MCP server 代码。

### 8. `mcp_client.py` — 自实现 MCP client

- 自实现 `tools/list`（发现工具）和 `tools/call`（调用）。
- 把 MCP server 的工具**注册进内核**，内核无感知地当作本地工具调用。
- 这是「client 端」——证明理解了协议全流程。

---

## 三、一次对话的完整数据流

以「帮我查一下 GPU 申请条件」为例：

```
1. 用户输入 → agent.py
2. agent.py 组装上下文（system prompt + 工具描述 + 历史 + 用户输入）
3. 调 llm.py → DeepSeek 返回：
   {"action": "knowledge_query", "action_input": {"query": "GPU 申请条件", "top_k": 3}}
4. parse_action 解析出「工具调用」
5. registry 找到 knowledge_query 工具 → 执行
6. 工具内部走 mcp_client → mcp_server → rag → ChromaDB 检索
7. 返回带来源的片段（观察结果）→ 写回历史
8. agent.py 再次调 llm.py（带上观察结果）→ 模型生成最终回答
9. 输出给用户（带来源引用）
```

---

## 四、ReAct 循环与工具调用协议

### 协议格式

模型被要求按固定 JSON 输出：

```json
{"action": "工具名", "action_input": {"参数": "值"}}
```

或最终回答：

```json
{"action": "final_answer", "action_input": "回答内容"}
```

- system prompt 里明确告诉模型这两种格式。
- 解析失败 → 走 json_repair 三层修复。

### 循环终止条件

- 模型输出 `final_answer`
- 达到 MAX_STEPS 上限（兜底）

---

## 五、上下文管理

**问题**：对话太长，模型上下文窗口装不下，或超长导致成本/延迟高。

**两个手段**（参考 OpenClaw agent-core）：

| 手段 | 做法 | 何时用 |
|------|------|--------|
| 截断 truncate | 直接砍掉最老的消息 | 常规超长 |
| 压缩 compact | 把旧对话总结成摘要 | 特别长时先压缩再截断 |

**SQLite schema**：

```sql
CREATE TABLE sessions (
  id TEXT PRIMARY KEY,
  created_at TEXT
);
CREATE TABLE messages (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  session_id TEXT,
  role TEXT,          -- user / assistant / tool
  content TEXT,
  created_at TEXT
);
```

**原则**：SQLite 存完整历史（不丢），送入模型前才做截断/压缩（窗口管理）。

---

## 六、MCP 两端

| 端 | 实现 | 关键点 |
|----|------|--------|
| server | 官方 `mcp` SDK | 注册 tool、JSON-RPC、参数 schema、返回 |
| client | 自实现 | `tools/list` 发现、`tools/call` 调用、解析结果 |

**为什么两端都写**：实习写过 server 端（会用 SDK），个人项目补 client 端（懂协议底层），两端都写过 = 理解 tool 生命周期全流程。

---

## 七、错误处理与可靠性

- 工具执行异常 → 捕获 → 错误信息作为观察回灌 → 让模型重试
- 非法 JSON → 三层修复 → 降级纯文本
- LLM 调用失败 → 重试 + 超时 + 降级提示
- MAX_STEPS 防死循环

---

## 八、目录结构约定

```
AgentKernel/
├── agent.py            # ReAct 主循环
├── llm.py              # 模型封装
├── tools/
│   ├── registry.py     # 工具注册
│   └── json_repair.py  # JSON 修复
├── memory/
│   └── sqlite_store.py # 记忆
├── rag/
│   └── ingest.py       # 文档入库
├── mcp_server/
│   └── kb_server.py    # MCP server
└── mcp_client.py       # MCP client
```

> 实现细节和按天任务见各阶段文档。
