# 这个项目在解决/探讨哪些真实生产问题

> AgentKernel 不是「又一个能对话的 Agent demo」。
> 它把 Agent 落地时最容易在生产里翻车的几类问题拆开，逐项实现、测试、评测，并明确剩余风险。

## 一句话

> 从零实现 Agent Runtime 的底层机制，并围绕**模型输出不可靠、上下文膨胀、多进程一致性、RAG 新鲜度/降级、MCP 工具边界、观测与成本、迁移安全、交付可重复**做工程验证；用测试、eval、trace 和回滚证据证明每一层，而不是只证明「能跑」。

## 30 秒版

实习用 Claude Agent SDK 交付业务，但 Runtime 被框架封装。为了搞清楚底层，我从零实现 ReAct、工具调用、MCP 和持久化检索；重点不是功能堆叠，而是把生产里最容易出问题的几类失败模式拆开：模型输出坏 JSON/乱调工具、上下文越聊越乱、多进程写同一会话、文档重复入库/向量依赖挂了、MCP 命令与密钥边界、token/成本看不见、schema 漂移、交付不可重复。每一类都用 fake LLM、故障输入、真实 MySQL、多进程和 CI 去验证，并记录剩余风险。

## 生产问题矩阵

| # | 真实生产问题 | 典型故障 | 本项目的设计与证据 | 剩余风险 / 下一步 |
|---|---|---|---|---|
| P1 | **模型输出不可靠** | 非法 JSON、代码围栏、未知工具、超长 payload、把长文本误判成工具调用 | 提取 → 修复 → 工具名 allowlist → 256KB 上限 → 纯文本降级；`tools/json_repair.py`；坏 JSON/未知工具/超长载荷测试 | 无 fallback 模型/供应商；provider 故障仍单点（G-23） |
| P2 | **上下文越聊越乱** | 早期约束丢失、历史撑爆上下文、压缩失败 | 保留首条用户要求；compact 摘要；摘要失败降级 truncate；`runtime/agent.py` 上下文策略；超预算/摘要失败/MAX_STEPS 测试 | 压缩质量无独立 eval；会话预算已落地（G-25） |
| P3 | **多进程写同一会话** | 进程内锁跨进程失效；丢失更新；`updated_at` 回退；1213/1205 死锁 | ADR-002 会话行锁 `SELECT ... FOR UPDATE`；有界 LRU；指数退避；20 进程 × 20 写用例进 CI | 同会话写串行（可接受）；未来高并发可评估幂等键方案 |
| P4 | **RAG 新鲜度与降级** | 重复入库、改文档后索引不更新、向量依赖挂了 | SHA-256 增量索引；稳定 `doc_id:ordinal`；MySQL ngram 基线；可选 Chroma + RRF；不可用回退 lexical；重复/变更/无向量测试 | mock/live golden set 已有（G-32）；Recall@5 未单列；Chroma 可选路径测试深度有限 |
| P5 | **MCP / 工具边界** | 任意命令启动子进程、继承 API key/DSN、文档路径穿越、symlink 逃逸、prompt injection | 命名 profile + 精确 argv；env 白名单；文档根 realpath；无 shell/eval；AST 计算器；副作用写工具需本地 y/N 审批 + 工作区沙箱；安全测试 | 工具结果已做不可信隔离（G-27）；出站 allowlist（G-24）；无 OS 级沙箱 |
| P6 | **观测与成本** | 只知道「跑完了」，不知道 token/成本/哪一步慢；日志含密钥 | JSONL 12 核心 + 条件字段；trace/turn/span；token/cost + 版本化定价；未知模型 `null`；写库前 redact + 4KB 截断；`make report/trace/prune` | 可选 OTLP/HTTP 导出（G-47）；会话预算（G-25）；审批/幂等审计字段；无 Prometheus 看板 |
| P7 | **Schema / 迁移安全** | `create_all` 与 Alembic 双轨；迁移回滚后表又被建回；误删数据无备份 | Alembic 0001/0002 往返测试；`make backup` + `make restore-drill` 首次演练 PASS；D4 选无 schema 变更方案 | 双轨 DDL 已收口（G-16）；备份是逻辑备份，RPO 需按部署确认 |
| P8 | **交付可重复** | 本地能跑、CI 不绿；镜像 root；体积失控；依赖漂移 | `uv.lock` + `.python-version`；CI MySQL service + 0-skip 强制；多阶段非 root 镜像 + 体积门禁；`make check` 单入口 | 基础镜像 digest 未 pin（G-45/G-46）；runbook/doctor 已完成（G-35/G-36） |

> 这张表就是项目的「生产问题主线」。面试时先讲问题，再讲取舍和证据，最后主动说剩余风险。

## 按问题展开

### P1 模型输出不可靠

**生产里为什么会出事**：模型不是编译器，输出可能带解释、单引号、代码围栏、截断或幻觉工具名；直接 `json.loads` 会崩，直接执行会误操作。

**做法**：五层兜底（提取 → 修复 → 工具名 allowlist → payload 上限 → 纯文本降级）；未知工具不执行；工具参数用纯 Python JSON Schema 子集校验；错误变成可读观察回灌，而不是让进程崩溃。

**证据**：`tests/test_json_repair.py`、`tests/test_agent.py`、`tests/test_registry.py`；坏 JSON/未知工具/超长载荷/非法参数用例。

**没解决**：没有备用模型/供应商切换；真实模型 live 用例只有冒烟级，不是大规模 eval。

### P2 上下文膨胀

**生产里为什么会出事**：长会话把早期约束挤掉；简单截断会丢关键要求；压缩本身可能失败或产生幻觉摘要。

**做法**：保留首条用户要求；超预算先 compact，失败再 truncate；`MAX_STEPS` 防死循环；上下文策略保持纯函数可测。

**证据**：超预算历史、摘要失败、MAX_STEPS、第 10 轮仍记得第 1 轮要求等用例。

**没解决**：压缩质量没有独立 eval；会话预算已落地（G-25），但预算耗尽的降级体验未做 eval。

### P3 多进程一致性

**生产里为什么会出事**：CLI 进程 + MCP 子进程/多客户端同时写同一会话时，进程内 `threading.Lock` 不共享；`updated_at` 可能回退；并发下 1213 死锁。

**做法**：ADR-002 选会话行锁 `SELECT ... FOR UPDATE`；写事务顺序固定；`updated_at` 在锁后取；有界 LRU；指数退避 + 抖动；20 进程 × 20 写用例进 CI。

**证据**：`docs/Addendum/adr-002-cross-process-session-writes.md`；`tests/test_mysql_multiprocess.py`；R10 从高风险降级。

**没解决**：同一会话写串行（CLI 场景可接受）；如果未来要求高并发写，需要评估幂等键/唯一约束方案。

### P4 RAG 新鲜度与降级

**生产里为什么会出事**：同一文档重复入库、文档更新后索引不更新、向量库/模型不可用导致检索直接失败。

**做法**：SHA-256 内容指纹 + 稳定 chunk id；MySQL ngram 作为持久化基线；Chroma 语义检索可选；RRF 融合；向量不可用回退 lexical，并提示原因。

**证据**：重复入库返回 0、修改后只重建该文档、无向量环境回退、删除文档等用例。

**没解决**：mock/live golden set 已有（G-32），但 Recall@5 未单列阈值；向量路径的故障注入还不够系统。

### P5 MCP / 工具边界

**生产里为什么会出事**：让 Agent 任意启动命令、继承父环境 API key/DSN、读任意路径、工具输出被当成可信指令。

**做法**：MCP 命名 profile + 精确 argv + 解释器白名单；子进程 env 白名单；文档根 realpath + 拒 symlink 逃逸；大小/数量/深度限制；无 shell/eval；AST 计算器。LLM 出站 `base_url` allowlist 已完成（G-24）。

**证据**：`tests/test_security.py`（15 个安全测试）、`mcp_profiles.example.toml`、路径越界/符号链接/超限/allowlist 绕过用例。

**没解决**：工具结果已做不可信隔离（G-27）；仍没有 OS 级沙箱（E2B/容器）作为第二道边界。

### P6 观测与成本

**生产里为什么会出事**：只看到「跑完了」，看不到哪一步慢、花了多少 token、错误率多少；日志里带密钥。

**做法**：每轮 1 条 `turn` + 每次工具 1 条 `tool`；JSONL 12 核心 + 条件字段（审批工具带 decision/reviewer/key/timestamp/summary）；trace/turn/span；token/cost + 版本化定价；未知模型 `null` 而不是 0；写库前 redact + 4KB 截断；`make report/trace/prune`。

**证据**：`tests/test_observability.py`；`docs/reports/2026-W44.md`；live 调用 tokens/cost 非空。

**没解决**：OTLP 可选导出已落地（G-47）；没有 Prometheus/外部指标看板与告警；会话预算已落地（G-25）。

### P7 Schema / 迁移安全

**生产里为什么会出事**：启动时 `create_all` 与 Alembic 双轨，schema 漂移；迁移回滚后表又被自动建回；误删无备份。

**做法**：Alembic 迁移 + 往返测试；`make backup` / `make restore-drill`；D4 方案选择无 schema 变更，降低回滚风险。

**证据**：`tests/test_migrations.py`；`docs/reports/restore-drill-20261029.md`；`make check` + CI MySQL service。

**没解决**：G-16 双轨 DDL 已收口；备份 RPO/保留策略要按真实部署再确认。

### P8 交付可重复

**生产里为什么会出事**：本地能跑、CI 不绿；镜像 root；体积失控；依赖漂移；上线没有回滚。

**做法**：`uv.lock` + `.python-version`；`make check` 单入口；CI MySQL service + 0-skip 强制；多阶段非 root 镜像 + 体积门禁；迁移与备份演练。

**证据**：CI workflow、`Dockerfile`、`docs/status.md`、`docs/reports/restore-drill-20261029.md`。

**没解决**：基础镜像 digest 未 pin（G-45/G-46）；runbook/doctor 已完成（G-35/G-36）。

## 这个项目不是什么

- 不是多租户 SaaS / Web 平台；
- 不是模型训练/微调项目；
- 不是 LangChain/LangGraph 替代品；
- 不宣称「已经生产可用」：它是**按生产标准建设的 CLI 研究原型**，明确列出残余风险。

## 面试叙事结构

1. **问题**：Agent 上生产最容易翻车的是哪几类失败模式？
2. **取舍**：每一类为什么选这个方案？备选是什么？为什么不选？
3. **证据**：测试、eval、trace、多进程、备份恢复、CI 怎么证明？
4. **边界**：哪些没解决？下一步是什么？
5. **反思**：如果重做，会先建哪条边界？

> 先讲问题，再讲设计，最后讲证据和剩余风险。不要从「我用了什么框架」开始。
