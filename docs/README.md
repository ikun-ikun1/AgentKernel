# AgentKernel 文档索引

> 先读 [status.md](./status.md)（单一事实源）。标准与阈值在 [production-standard.md](./production-standard.md)，逐项差距在 [production-standard-gap.md](./production-standard-gap.md)。
> 历史里程碑与面试材料是**当时快照**，数字不随 CI 更新；当前数字一律以 status.md 为准。

## 1. 现状与标准（先读）

| 文档 | 内容 |
|---|---|
| [status.md](./status.md) | 测试/CI/镜像/观测现状、批一交付、未完成 Top 风险、复现命令 |
| [production-problems.md](./production-problems.md) | **这个项目在解决/探讨哪些真实生产问题**：P1–P8 故障模式、设计、证据、残余风险 |
| [production-standard.md](./production-standard.md) | 项目画像、SLO 与错误预算、威胁模型、六门禁阈值、发布回滚、豁免 |
| [production-standard-gap.md](./production-standard-gap.md) | 41+ 项差距：现状证据、风险、优先级、验收标准 |
| [reports/](./reports/) | `make report` 的 SLO 周报与索引（含真实 API 的 `2026-W44`）；`restore-drill-*.md` 为恢复演练证据；`incident-20261030-schema-drift.md` 为首次事故复盘 |

## 2. 设计与边界

| 文档 | 内容 |
|---|---|
| [project-background.md](./project-background.md) | 为什么做、与实习项目 AI Agent Workbench 的互补关系 |
| [technical-scope-and-boundary.md](./technical-scope-and-boundary.md) | 技术选型、模块边界、硬边界、安全边界 |
| [architecture.mmd](./architecture.mmd) / [architecture.png](./architecture.png) | 当前架构图（MySQL 事实源 + 观测 + MCP profile）；目标边界见 ADR-003 |
| [Addendum/adr-001-mysql-primary-storage.md](./Addendum/adr-001-mysql-primary-storage.md) | ADR-001：MySQL 8 作为主存储 |
| [Addendum/adr-002-cross-process-session-writes.md](./Addendum/adr-002-cross-process-session-writes.md) | ADR-002：跨进程会话写一致性（D4，Accepted） |
| [Addendum/adr-003-production-architecture.md](./Addendum/adr-003-production-architecture.md) | ADR-003：生产级模块边界与增量重构（架构 A0，Proposed） |

## 3. 运行与交付

| 文档 | 内容 |
|---|---|
| [runbook.md](./runbook.md) | 6 个事故场景：判定 → 止血 → 恢复 → 验证 → 回滚（含事故记录模板） |
| [../CHANGELOG.md](../CHANGELOG.md) | 版本变更记录（Keep a Changelog，当前 `0.2.0`） |
| [../README.md](../README.md) | 快速开始、常用命令、目录结构 |
| [../mcp_profiles.example.toml](../mcp_profiles.example.toml) | MCP profile 示例（精确 argv + env 白名单） |
| [Addendum/demo-script.md](./Addendum/demo-script.md) | 演示脚本（历史，命令以 README 为准） |

## 4. 历史里程碑（2026-09）

| 文档 | 内容 |
|---|---|
| [milestone-1-kernel.md](./milestone-1-kernel.md) | M1：ReAct 内核可跑 |
| [milestone-2-mcp.md](./milestone-2-mcp.md) | M2：MCP 协议与示例工具链 |
| [milestone-3-deliverables.md](./milestone-3-deliverables.md) | M3：交付物与缓冲 |

## 5. 附录与面试材料

| 文档 | 内容 |
|---|---|
| [Addendum/learning-map.md](./Addendum/learning-map.md) | 教学映射（agent-study ↔ OpenClaw ↔ Workbench） |
| [Addendum/self-review.md](./Addendum/self-review.md) | 与 Claude Agent SDK / 高星 MCP 库的对照自评 |
| [Addendum/framework-comparison-deepseek-harness.md](./Addendum/framework-comparison-deepseek-harness.md) | 与 DeepSeek Harness 的框架对比 |
| [Addendum/resume-and-interview.md](./Addendum/resume-and-interview.md) | 简历 bullet 与面试话术 |
| [agentkernel-interview-blueprint.html](./agentkernel-interview-blueprint.html) | 面试蓝图（HTML） |

## 6. 维护规则

1. **数字只写一处**：测试数、CI 状态、镜像体积写 `status.md`；其他文档引用它，不复制。
2. **标准与差距分离**：`production-standard.md` 只写「要求与阈值」，`production-standard-gap.md` 只写「现状/证据/优先级」。
3. **历史文档不改写**：里程碑与面试材料保持当时快照；如与现状冲突，以 status/README 为准并加「历史」标注。
4. **报告入 git**：`docs/reports/` 是发布证据，不删除。
