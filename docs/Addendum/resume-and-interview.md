# 简历与面试材料

> **历史文档（2026 年快照）**：命令与数字为当时状态；当前状态见 [../status.md](../status.md)。
> 投递请使用下面的「当前版（v0.4.0）」；历史快照保留用于展示演进。

## 当前版（v0.4.0，2026-10-30，投递用）

> 下面这版数字与命令以 [status.md](../status.md) 为准；本文件后面的内容是 2026-09 历史快照，仅用于看演进。

**AgentKernel · 自研 Agent Runtime + 知识库 MCP（Python，个人项目）**

- 从零实现 ReAct Runtime、工具调用、MCP client/server、MySQL 会话/审计、RAG 检索与合并；不依赖 Agent 框架。
- 按「真实失败模式 → 设计取舍 → 测试/评测证据 → 剩余风险」推进：坏 JSON/未知工具、上下文膨胀、多进程丢更新、RAG 新鲜度、MCP/路径/密钥边界、迁移回滚、可重复交付。
- 架构按 ports & adapters 落地：LLM/Memory/MCP 端口注入，Agent 184 行 facade，RAG/MCP/CLI 拆分；canonical import 路径稳定，v0.4.0 删除兼容 shim（Breaking，迁移表可查）。
- 质量证据：**203 tests**、覆盖率 **84%**、CI MySQL 8 + 0 skip、mock eval 50/50、600 条 fuzz 语料 0 崩溃、make doctor 7 项、备份/恢复演练 PASS、镜像 digest 固定。
- 边界：CLI 研究原型，按可上生产标准建设，但不宣称线上 SLA/多租户/高并发生产系统。

### 当前版 2 分钟叙事

1. **问题**：Agent 框架把 Runtime 封装了；真正上生产时坏 JSON、上下文膨胀、多进程写、RAG 过期、MCP 权限、观测和回滚才是事故源。
2. **基线**：先复现 ReAct、工具契约、观察回灌和持久化，明确模型文本如何变成受控动作。
3. **失败模式**：逐项做防护——五层 JSON 修复/白名单/降级，truncate/compact，会话行锁 + 重试，SHA-256 增量索引 + 词法基线 + 可选向量，MCP profile + env/路径/allowlist，JSONL/trace/成本/OTLP。
4. **工程化**：用 ports & adapters 固定边界，LLM 端口真正注入；Agent 缩到 184 行 facade；每步独立 PR，测试/迁移/多进程/安全用例持续绿。
5. **证据与边界**：203 tests、84% 覆盖、CI 0 skip、eval/fuzz/doctor/恢复演练；v0.4.0 是稳定冻结点，旧 shim 按弃用路径删除，下一步只做维护/性能。

---



> 以下表述已通过本机 MySQL 测试（测试数量以 [../status.md](../status.md) 为准；含 3 个 MySQL 集成 + 1 个迁移往返 + 多进程一致性）和 mock 评估（5/5）验证。

## 项目描述（简历版）

**AgentKernel · 自研 Agent 内核与知识库 MCP 工具**，Python，个人项目，独立完成

- **项目背景**：实习用 Claude Agent SDK 交付业务，但 Runtime 被框架封装；为学习底层，参考 agent-study 复现最小 Agent 内核，并参考 OpenClaw 的工具调用修复思路，围绕模型输出不稳定、知识库更新不可靠做改进。
- **核心工作**：
  - 自研 ReAct 主循环、工具注册、观察回灌、持久化记忆；MySQL 8 主存储，SQLAlchemy + Alembic 管理连接与迁移。
  - 模型输出五层兜底（参考 OpenClaw）：提取 JSON、规范格式、工具名白名单、256KB 上限、降级纯文本；truncate/compact 防上下文超限。
  - RAG：MySQL ngram 关键词检索 + 可选 Chroma 语义检索，RRF 融合；向量不可用退回关键词，SHA-256 指纹增量更新。
  - MCP：自研 Client（初始化、工具列表、调用）；Server 支持官方 SDK 或纯 stdio。
- **验证**：按「成功路径、失败路径、边界条件」设计测试，用假 LLM 固定模型输出；测试用例（数量以 [../status.md](../status.md) 为准；含 MySQL 集成、迁移往返与多进程一致性；无 DSN 时跳过 4 个 DSN 用例）、5 个 mock eval 通过；CLI 跑通多轮对话、工具调用、知识库带来源、坏 JSON 不崩。
- **学习延伸**：学习 DeepSeek Harness 的 Profile/Bundle 声明式组装与 JSONL 会话事件日志/投影，思考可借鉴点。
- **成果**：个人研究原型，未投入生产，与实习互补。

## 30 秒介绍

实习用 Claude Agent SDK 交付业务，但 Runtime 被框架封装。为学习底层，我参考 agent-study 复现最小 Agent 内核，参考 OpenClaw 做模型输出治理，围绕模型输出不稳定和知识库更新不可靠两个问题做改进，并用测试和评估脚本验证。

## 2 分钟介绍结构

1. **问题**：框架让 Agent 应用交付更快，但 Runtime 底层不可见；为学习底层，先复现关键机制，再围绕模型输出稳定性和知识库更新可靠性做优化。
2. **基线**：参考 agent-study 实现 ReAct 主循环、工具调用和观察回灌，明确模型输出文本如何转换成受控动作。
3. **输出治理**：参考 OpenClaw 的分层修复思路，做提取 JSON、规范格式、工具名白名单、256KB 上限、降级纯文本五层兜底，处理坏 JSON 和误识别风险。
4. **检索优化**：用 SHA-256 判断是否需要重建；文档和 Chunk 写入 MySQL，用 ngram 全文检索做词法基线；向量依赖可用时叠加 Chroma，用 RRF 合并两路候选，失败时退回 MySQL 检索。
5. **协议**：MCP client 自己实现 Content-Length 帧和 JSON-RPC 请求，server 只暴露只读知识工具，结果包含 source/page 元数据。
6. **互补**：Workbench 负责 Web、业务 Agent、审批和企业治理；AgentKernel 负责底层原理学习和问题优化，不重复做业务平台。

## 高频问题

### 1. 为什么不直接使用 Claude Agent SDK？

Workbench 证明我能直接使用 SDK 交付业务；AgentKernel 的目标不同，是把 SDK 隐藏的 ReAct、工具协议、上下文和失败处理机制拆出来做最小验证，不追求替代 SDK。

**代码位置**：`runtime/agent.py`（ReAct 主循环）、`tools/contracts.py`（调用契约）、`tools/json_repair.py`（坏 JSON 修复）、`tools/registry.py`（参数校验）。

### 2. 为什么 RAG 不放在 Workbench 里？

Workbench 负责制度问答等业务编排；AgentKernel 用一个小型检索样例验证 Runtime 如何接入外部状态、处理文档更新并保留来源。这样可以独立观察底层行为，也避免把业务权限和文档管理耦合到 Runtime。

**代码位置**：`rag/ingest.py`（检索样例）、`mcp/server.py`（只读工具适配）。

### 3. 为什么同时保留 MySQL ngram 和向量检索？

MySQL ngram 词法检索对专有名词、错误码和精确短语稳定，向量检索对语义改写更好。两者候选集合互补，RRF 不要求不同分数空间可直接比较。

**代码位置**：`rag/ingest.py` 的 `KnowledgeBase.query`（hybrid 分支做 RRF 融合）、`rag/mysql_store.py` 的 `MySQLKnowledgeStore.lexical_query`（ngram 词法查询）。

### 4. 文档重复入库如何处理？

以规范化路径生成 `doc_id`，以文件 SHA-256 判断内容是否变化；未变化直接跳过，变化则在事务中删除旧 Chunk、写入新 Chunk，并使用稳定的 `doc_id:ordinal` 生成 Chunk ID。

**代码位置**：`rag/ingest.py` 的 `_sha256_file`、`KnowledgeBase.ingest_file`（checksum 命中 return 0）、`rag/mysql_store.py` 的 `MySQLKnowledgeStore.upsert_document`（事务内重建）。

### 5. 向量模型下载失败怎么办？

MySQL ngram 是持久化基线。词法后端不依赖向量模型；`hybrid/auto` 初始化失败时明确记录降级原因，回退到 MySQL 检索；`semantic` 则 fail-fast。

**代码位置**：`rag/ingest.py` 的 `KnowledgeBase.__init__`（auto/hybrid 降级、semantic 抛错）和 `_VectorIndex`。

### 6. 来源引用如何保证？

Chunk 保存 `source`、`page`、`section` 和 `doc_name`，SearchResult 携带这些元数据，最终由 `to_citation()` 统一格式化。引用来自检索结果，不由模型凭空生成。

**代码位置**：`rag/ingest.py` 的 `Chunk` / `SearchResult.to_citation()`；MCP 侧 `mcp/server.py` 的 `format_results`。

### 7. 为什么 MCP 不直接用官方 SDK？

server 端提供官方 SDK 可选实现和纯 Python stdio 入口；client 端自实现是为了理解协议边界，包括帧长度、请求 ID、初始化协商、错误响应和 `structuredContent`。

**代码位置**：`mcp/framing.py`（Content-Length 帧）、`mcp/client.py` 的 `StdioMCPClient`（`initialize`、`tools/list`、`tools/call`）、`mcp/server.py` 的 `handle_json_rpc` / `run_stdio`。

### 8. 这个项目和 Workbench 的边界是什么？

Workbench 是应用和治理层：Web、业务 Agent、审批、权限、会话和审计。AgentKernel 是原理研究层：最小 ReAct、Tool Calling、MCP wire protocol，以及用于验证外部状态接入的检索样例。两者互补，不是两个业务产品。

**代码位置**：`docs/technical-scope-and-boundary.md` 第 2 节（系统边界表）、`docs/project-background.md` 1.2（硬边界）。

### 9. DeepSeek Harness 对比延伸是怎么回事？

完成自研 Runtime 后，学习本地 `dsh-handbook` / `deepseek-harness-handbook` 与官方包源码：dsh 用 Profile/Bundle/Patch 声明式组装、Cordis 扩展点、JSONL 会话事件日志与投影。收获是理解生产级框架的组装与容错设计，并思考哪些设计可借鉴到项目里。

**代码位置**：`docs/Addendum/framework-comparison-deepseek-harness.md`。
