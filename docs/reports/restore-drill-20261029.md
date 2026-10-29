# 恢复演练报告 · 2026-10-29

- 结论：**PASS**
- 备份文件：`backups/agentkernel-20261029-165805.sql.gz`（0.00 MB，age=0.0h）
- 临时库：`agentkernel_restore_drill`（演练后删除）
- 恢复耗时：**0.9s**（RTO 目标 ≤ 1800s）
- 备份年龄：**0.0h**（RPO 目标 ≤ 24h）
- 执行方式：docker；应用账号：agentkernel

| 表 | 源库 | 恢复库 | 结果 |
|---|---|---|---|
| sessions | 2 | 2 | OK |
| messages | 6 | 6 | OK |
| tool_logs | 3 | 3 | OK |
| documents | 1 | 1 | OK |
| chunks | 1 | 1 | OK |

> 由 `make restore-drill` 生成；口径见 docs/production-standard.md §4.3。
