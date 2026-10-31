# AgentKernel 面试 Case Study

> 一页版：问题 → 方案 → 证据 → 取舍 → 边界。数字以 [status.md](./status.md) 为准；这是 CLI 研究原型，不是线上生产系统。

## 1. 问题：Agent 上生产的 6 类失败模式

1. **模型输出与工具边界不可靠**：坏 JSON、未知工具、超长 payload、任意 MCP 命令、路径/密钥泄露、工具结果注入。
2. **上下文膨胀**：长会话挤掉早期约束；简单截断丢关键要求；压缩本身可能失败。
3. **多进程写同一会话**：进程内锁跨进程失效、updated_at 回退、1213/1205 死锁。
4. **RAG 新鲜度与降级**：重复入库、改文档不更新、向量依赖不可用时检索直接失败。
5. **观测与成本不可见**：不知道哪一步慢、花了多少 token/成本；日志带密钥。
6. **迁移与交付不可重复**：schema 双轨/漂移、回滚无锚点、本地能跑 CI 不绿、镜像漂移。

## 2. 方案：每一类怎么解

- **Runtime**：自研 ReAct 主循环；工具契约 + 名字白名单 + JSON Schema 子集；五层 JSON 修复（提取/修复/白名单/256KB/纯文本降级）；上下文 truncate/compact。
- **MCP 与工具边界**：命名 profile + 精确 argv；子进程 env 白名单；文档根 realpath + symlink 防逃逸；工具结果用不可信标记隔离；LLM 出站 allowlist。
- **RAG**：SHA-256 增量索引；MySQL ngram 词法基线；可选 Chroma + RRF，失败回退 lexical；引用带 source/page。
- **审批写工具**：write_workspace_file 只写工作区（64KB、拒绝 ../、绝对路径、symlink）；requires_approval + 注入式 approval_fn，CLI y/N 默认拒绝；审批/幂等审计进 tool 事件；单进程幂等去重。
- **真实评测**：24 条真实任务（工具选择/参数/坏输入/RAG/多步），runner 带成本上限、超时、重试；mock 50 条继续守 CI 回归。

## 3. 证据

| 项 | 结果 |
|---|---|
| 测试 | **227 tests**；本地 221 passed / 6 skipped；CI 226 passed / 1 deselected / 0 skipped |
| 覆盖率 | **84.87%**（门槛 80%） |
| mock eval | **50/50**（CI 门禁） |
| live eval | 24 条真实任务：**首轮 23/24**，澄清 1 条歧义任务后 **24/24**；成功率 100%（仅限该任务集） |
| live 延迟/成本 | p50 **1117.81ms** / p95 **1769.88ms**；tokens 20461 / 1331；成本 **$0.006988** |
| 质量门禁 | make check、make doctor 7/0、600 条 fuzz 0 崩溃、备份/恢复演练 PASS、镜像 digest 固定 |
| 架构 | A0–A7 ports & adapters；Agent 184 行 facade；v0.4.0 删除 shim |

## 4. 取舍：为什么停在这里

- 不做多租户/Web/RBAC/微服务/async 重写：单用户 CLI 没有这些真实入口，做了无法用测试和 SLO 证明，只会增加面试时讲不清的复杂度。
- 不引入 DI 容器/更多架构层：只对 LLM、Memory、MCP 三个真实边界做端口；其余保持简单。
- 审批只做本地 CLI y/N，不做审批平台/can_use_tool 产品：单用户场景下平台化收益低。
- 停在 **v0.5.0**：P0-1 审批写工具 + P0-2 真实评测完成；继续加功能不再提高“可上生产”的可信度，维护/性能更有价值。

## 5. 边界：没做什么

- 24 条 live 样本有限，不能外推为泛化能力；首轮 23/24 的修正已保留，不写成“首次即 100%”。
- 外部 MCP 工具没有统一 requires_approval；审批目前只覆盖内置 write_workspace_file，MCP 审批是 P1。
- 幂等只在单进程内（LRU），跨进程持久化幂等未做；tool_logs 表也没有审批列，审批审计以 JSONL tool 事件为准。
- 未做 OS 级沙箱；symlink resolve 到写入存在极窄 TOCTOU 窗。
- 不是生产系统：无线上 SLA、无 7×24 on-call、无多租户/企业鉴权。
