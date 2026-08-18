# 阶段 2：知识库 MCP 打通（第 2 周）

> 目标：**问「XX 是什么」→ 检索回答带来源**。
> 优先级：🟡 重要（至少完成 D1-D5 的 RAG + MCP 打通）。

---

## 验收标准（本阶段完成的定义）

- [ ] 文档能入库（PDF/MD/TXT）
- [ ] `knowledge_query` 能检索出相关片段并带来源
- [ ] Agent 通过 MCP 调知识库，回答带来源

---

## 前置准备

- [ ] 装好 ChromaDB + sentence-transformers（bge-small-zh），pip 一把梭
- [ ] 准备好测试文档（2-3 篇 PDF/MD，内容你自己熟，方便验证）

---

## D1-2：文档解析 + 分块 + 向量化入库 🟡

**目标**：把文档变成能检索的向量。

- [ ] `rag/ingest.py`：解析 PDF（PyMuPDF）/ MD（markdown-it-py）/ TXT
- [ ] 分块：按标题/段落切，块间带重叠
- [ ] 向量化：bge-small-zh → 存入 ChromaDB
- [ ] 检索：query 向量化 → top_k 召回

**验收**：喂一个 query，能召回相关片段。

**踩坑提示**：
- 分块重叠是防止信息被切碎，重叠量一般 10-20% 块长
- 先小规模验证（几篇文档），再跑大批量

---

## D3-4：mcp_server 注册两个 tool 🟡

**目标**：知识库能力暴露成 MCP 工具。

- [ ] `mcp_server/kb_server.py`：用官方 `mcp` SDK
- [ ] 注册 `knowledge_query(query, top_k)`：检索 + 带来源
- [ ] 注册 `knowledge_list()`：列出已入库文档
- [ ] 参考实习 M3 的 MCP server 代码

**验收**：MCP server 能独立启动，工具能被发现和调用。

**踩坑提示**：
- tool 的 JSON Schema 要写全（参数名/类型/描述）
- 返回结果带上来源（文档名 + 片段），这是「带来源」的关键

---

## D5：自实现 mcp client + 打通 Agent → MCP → 知识库 🟡

**目标**：内核通过 MCP 调知识库，无感知。

- [ ] `mcp_client.py`：实现 `tools/list`（发现）+ `tools/call`（调用）
- [ ] 把 MCP 工具注册进内核的 registry，当作普通工具
- [ ] 打通全链路：Agent → MCP client → MCP server → RAG → ChromaDB

**验收**：问「XX 是什么」，Agent 自动调 knowledge_query，回答带来源。

**踩坑提示**：
- MCP 协议流程：`initialize` → `tools/list` → `tools/call`，顺序别乱
- client 端是重点（证明懂底层），别偷懒用现成 client

---

## D6-7：测试 + 修 bug 🟡

**目标**：跑通 5 个评估用例（至少核心 3 个）。

- [ ] 正常问答
- [ ] 工具调用
- [ ] 知识库问答（带来源）
- [ ] 坏 JSON 不崩（回归）
- [ ] 上下文保持（多轮）

**验收**：5 用例全过，或至少核心用例过。

---

## 本阶段产出

- [ ] 知识库入库 + 检索
- [ ] MCP server（官方 SDK）+ MCP client（自实现）
- [ ] 打通「Agent → MCP → 知识库」链路

## 卡壳 2 小时法则

> 一个东西搞 2 小时没通 → 停下来问小爪，或先跳过做别的，不硬扛。
