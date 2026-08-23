# 里程碑 2：知识库 MCP 打通

> **当前进度**：✅ 已实现。RAG 文档解析/分块/检索（ChromaDB 可选 + 纯 Python 降级索引）、MCP server（官方 SDK 可选 + 纯 Python stdio 入口 `python -m agentkernel.mcp.server`）、自实现 MCP client（Content-Length 帧 + JSON-RPC 2.0，含 stdio 子进程集成测试）已打通；`tests/test_rag.py`、`tests/test_mcp.py` 覆盖核心链路。

## 周期与验收要求

- 周期：2026-09-09 ~ 2026-09-18（第 2 周）。
- 验收要求：9/18 前完成里程碑验收。
- 验收方式：功能演示 + 代码走读 + 评估用例跑通。

## 阶段目标

在 M1 内核基础上，接入知识库：文档入库 → 向量检索 → 通过 MCP 暴露成工具 → 内核无感知调用，实现「问 XX 是什么 → 检索回答带来源」。

本阶段重点是打通「Agent → MCP → 知识库」链路，证明 MCP 两端都写过。

## 设计思路

分两半：先把 RAG 跑通（文档 → 向量 → 检索），再用 MCP 包一层暴露给内核。

```
Agent → mcp/client.py（自实现 tools/list + tools/call）
     → mcp/server.py（官方 SDK，注册 knowledge_query / knowledge_list）
     → rag/ingest.py（文档 → 分块 → bge 向量化 → ChromaDB）
     → 检索返回带来源片段
```

关键点：

1. server 端用官方 `mcp` SDK，不重复造轮子；client 端自实现，证明懂协议底层。
2. 检索结果必须带来源（文档名 + 片段），这是「带来源」的关键。
3. MCP 工具注册进内核 registry，内核当作普通工具调用，无感知。

## 模块与目的

1. `rag/ingest.py`  
目的：解析 PDF（PyMuPDF）/ MD / TXT（MD/TXT 按 UTF-8 文本读取）→ 分块（带重叠）→ bge-small-zh 向量化 → 存入 ChromaDB。

2. `mcp/server.py`  
目的：用官方 `mcp` SDK 暴露 2 个工具——`knowledge_query(query, top_k)` 检索带来源、`knowledge_list()` 列出已入库文档。

3. `mcp/client.py`  
目的：自实现 MCP client（`initialize` → `tools/list` → `tools/call`），把 MCP 工具注册进内核。

## 交付物

1. 知识库入库 + 检索能力。
2. MCP server（官方 SDK）+ MCP client（自实现）。
3. 打通「Agent → MCP → 知识库」链路。
4. 至少 1 个测试文档（内容自己熟，方便验证）。

## 任务拆解

### D1-2：文档解析 + 分块 + 向量化入库

- `rag/ingest.py`：解析、分块（带重叠）、向量化、入库。
- 检索：query 向量化 → top_k 召回。

### D3-4：mcp/server 注册两个 tool

- `mcp/server.py`：注册 `knowledge_query` + `knowledge_list`。
- 参考实习 M3 的 MCP server 代码。

### D5：自实现 mcp client + 打通链路

- `mcp/client.py`：`tools/list` + `tools/call`。
- 把 MCP 工具注册进内核 registry。
- 打通 Agent → MCP → 知识库。

### D6-7：测试 + 修 bug

- 跑 5 个评估用例（至少核心 3 个）：正常问答 / 工具调用 / 知识库问答 / 坏 JSON 回归 / 上下文保持。

## 验收标准

1. 文档能入库（PDF/MD/TXT）。
2. `knowledge_query` 能检索出相关片段并带来源。
3. Agent 通过 MCP 调知识库，回答带来源。
4. 5 个评估用例全过，或至少核心用例过。

## 阶段 2 验收记录（2026-08-19）

| 验收项 | 结果 | 证据 |
|--------|------|------|
| 文档入库（MD/TXT；PDF 依赖 PyMuPDF） | ✅ | `tests/test_rag.py`：load_document / chunk_text / ingest_file |
| `knowledge_query` 带来源检索 | ✅ | `tests/test_mcp.py`：输出含 `[来源：notes.md]` |
| Agent → MCP → 知识库链路 | ✅ | `eval.py` 用例 4（mock）；`tests/test_mcp.py::test_register_mcp_tools_into_registry` |
| 自实现 MCP client 真连 stdio server | ✅ | `tests/test_mcp.py::test_stdio_client_against_self_hosted_server` |
| 5 个评估用例 | ✅ mock 5/5；live 5 用例（4 个真实 API + 1 个解析层坏 JSON，依赖 API 可用性） | `python eval.py` / `python eval.py --live` |
| CLI 知识库演示 | ✅ | `python -m agentkernel --docs <路径>`，`/docs`、`/ingest`、`/logs` |
| ChromaDB 可选后端 | ✅ | CLI `--kb-db <目录>`；未装依赖自动降级纯 Python 索引 |

## 明确不做

1. 不做混合检索 / 重排（知道思路、口头能讲即可）。
2. 不做真实企业知识库接入。
3. 不做多文档库 / 复杂权限。
4. 不做 Web 界面。

## 踩坑提示

- 分块重叠量一般 10-20% 块长，防止信息被切碎。
- MCP 协议流程 `initialize` → `tools/list` → `tools/call`，顺序别乱。
- 先小规模验证（几篇文档），再跑大批量。
- 卡壳 2 小时 → 停下来问小爪，或先跳过做别的，不硬扛。
