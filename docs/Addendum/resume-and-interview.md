# 简历与面试材料

> 以下 MySQL、SQLAlchemy、Alembic 和集成测试表述适用于 ADR-001 完成代码迁移并通过验收后的简历版本；迁移完成前不要对外宣称已使用。

## 简历 Bullet

**Agent Runtime 原理研究与 MCP 检索实验**，Python，个人项目，独立完成

- 参考 agent-study 复现 ReAct、工具注册、观察回灌和持久化记忆等 Agent 基线，并以实习项目中的 Claude Agent SDK 为对照，拆解框架隐藏的 Runtime 行为。
- 针对模型输出不稳定问题，参考 OpenClaw 的工具调用修复思路，实现“平衡结构提取 → JSON 格式修复 → 工具名 allowlist/payload 上限校验 → 纯文本降级”链路，避免普通文本被误执行或异常输出导致 Agent 崩溃。
- 针对文档重复入库、内容更新和向量依赖不可用问题，使用 MySQL 8 持久化文档元数据与 Chunk，结合 ngram 全文检索、可选 Chroma 向量检索和 RRF 融合，并保留来源信息作为可验证的检索实验。
- 自实现 MCP stdio/JSON-RPC 2.0 client，完成 `initialize`、`tools/list`、`tools/call`、错误映射和外部工具注册；server 侧提供官方 SDK 可选适配和纯 Python stdio 实现，将检索样例以只读 MCP 工具接入 Runtime。
- 通过 59 个测试用例（另有 2 个 MySQL 集成测试按需启用）、5 个 mock 评估用例和故障场景验证，覆盖持久化恢复、增量重建、工具回灌、坏 JSON 降级、上下文压缩回退和 MCP 子进程链路。

## 30 秒介绍

实习项目 AI Agent Workbench 让我直接使用 Claude Agent SDK 完成了 Web 工作台的应用交付。为了理解 SDK 隐藏的 Agent Loop、工具调用、上下文管理和 MCP 边界，我参考 agent-study 先复现 Agent 基线，再参考 OpenClaw 的成熟工程思路，针对模型输出可靠性和文档增量更新做优化。前者证明我能使用框架交付，后者证明我能学习原理并围绕问题改进实现。

## 2 分钟介绍结构

1. **问题**：框架让 Agent 应用交付更快，但 Runtime 的底层行为不可见；因此先复现关键机制，再选择模型输出可靠性和文档更新两个具体问题做优化。
2. **基线**：参考 agent-study 实现 ReAct、工具调用和观察回灌，明确模型输出文本如何转换成受控动作。
3. **可靠性优化**：参考 OpenClaw 的分层修复思路，加入结构提取、格式修复、allowlist、payload 上限和纯文本降级，处理坏 JSON 和误识别风险。
4. **检索优化**：用 checksum 判断是否需要重建；文档分块后写入 MySQL 文档目录、Chunk 表并使用 ngram 全文检索；向量依赖可用时写入 Chroma，并用 RRF 合并词法与语义候选，失败时保留 MySQL 检索基线。
5. **协议**：MCP client 自己实现 Content-Length 帧和 JSON-RPC 请求，server 只暴露只读知识工具，结果包含 source/page 元数据。
6. **互补**：Workbench 负责 Web、业务 Agent、审批和企业治理；AgentKernel 负责原理复现和问题优化，不重复做业务平台。

## 高频问题

### 1. 为什么不直接使用 Claude Agent SDK？

Workbench 证明我能直接使用 SDK 交付业务；AgentKernel 的目标不同，是把 SDK 隐藏的 ReAct、工具协议、上下文和失败处理机制拆出来做最小验证，不追求替代 SDK。

**代码位置**：`runtime/agent.py`（ReAct 主循环）、`tools/contracts.py`（调用契约）、`tools/json_repair.py`（坏 JSON 修复）、`tools/registry.py`（参数校验）。

### 2. 为什么 RAG 不放在 Workbench 里？

Workbench 负责制度问答等业务编排；AgentKernel 用一个小型检索样例验证 Runtime 如何接入外部状态、处理文档更新并保留来源。这样可以独立观察底层行为，也避免把业务权限和文档管理耦合到 Runtime。

**代码位置**：`rag/ingest.py`（检索样例）、`mcp/server.py`（只读工具适配）。

### 3. 为什么同时保留 MySQL ngram 和向量检索？

MySQL ngram 词法检索对专有名词、错误码和精确短语稳定，向量检索对语义改写更好。两者候选集合互补，RRF 不要求不同分数空间可直接比较。

**代码位置**：迁移后对应 `KnowledgeBase.query` 的 hybrid 分支和 MySQL Repository 的 ngram 词法查询。

### 4. 文档重复入库如何处理？

以规范化路径生成 `doc_id`，以文件 SHA-256 判断内容是否变化；未变化直接跳过，变化则在事务中删除旧 Chunk、写入新 Chunk，并使用稳定的 `doc_id:ordinal` 生成 Chunk ID。

**代码位置**：`rag/ingest.py` 的 `_sha256_file`、`KnowledgeBase.ingest_file`（checksum 命中 return 0）和迁移后的 MySQL Repository（事务内重建）。

### 5. 向量模型下载失败怎么办？

MySQL ngram 是持久化基线。词法后端不依赖向量模型；`hybrid/auto` 初始化失败时明确记录降级原因，回退到 MySQL 检索；`semantic` 则 fail-fast。

**代码位置**：`rag/ingest.py` 的 `KnowledgeBase.__init__`（auto/hybrid 降级、semantic 抛错）和 `_VectorIndex`。

### 6. 来源引用如何保证？

Chunk 保存 `source`、`page`、`section` 和 `doc_name`，SearchResult 携带这些元数据，最终由 `to_citation()` 统一格式化。引用来自检索结果，不由模型凭空生成。

**代码位置**：`rag/ingest.py` 的 `Chunk` / `SearchResult.to_citation()`；MCP 侧 `mcp/server.py` 的 `format_results`。

### 7. 为什么 MCP 不直接用官方 SDK？

server 端提供官方 SDK 可选实现和纯 Python stdio 入口；client 端自实现是为了理解协议边界，包括帧长度、请求 ID、初始化协商、错误响应和 `structuredContent`。

**代码位置**：`mcp/framing.py`（Content-Length 帧）、`mcp/client.py` 的 `StdioMCPClient`（`initialize → tools/list → tools/call`）、`mcp/server.py` 的 `handle_json_rpc` / `run_stdio`。

### 8. 这个项目和 Workbench 的边界是什么？

Workbench 是应用和治理层：Web、业务 Agent、审批、权限、会话和审计。AgentKernel 是原理研究层：最小 ReAct、Tool Calling、MCP wire protocol，以及用于验证外部状态接入的检索样例。两者互补，不是两个业务产品。

**代码位置**：`docs/technical-scope-and-boundary.md` 第 2 节（系统边界表）、`docs/project-background.md` 1.2（硬边界）。

### 9. DeepSeek Harness 对比延伸是怎么回事？

完成自研 Runtime 后，研读本地 `dsh-handbook` / `deepseek-harness-handbook` 与官方包源码，从应用开发视角对比：dsh 用 Profile/Bundle/Patch 声明式组装、Cordis 扩展点、JSONL 会话投影，AgentKernel 用固定 Runtime 教学实现。收获是理解生产级框架的组装与容错设计，而不是重写一个 dsh。

**代码位置**：`docs/Addendum/framework-comparison-deepseek-harness.md`。
