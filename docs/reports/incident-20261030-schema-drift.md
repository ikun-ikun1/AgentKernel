# Incident 2026-10-30：本地库 schema 漂移导致迁移 1060

- **发现时间**：2026-10-30 14:00 前后（CST）
- **恢复时间**：同日 14:10 前后
- **影响时长**：约 10 分钟（仅本地开发库）
- **严重级别**：Low
- **影响面**：本机 `agentkernel` 开发库。`python -m agentkernel --migrate` 会因 `Duplicate column name 'duration_ms'` 失败；CLI 读写与既有数据不受影响，无生产/线上影响。
- **SLO**：未触及（本地开发环境，不计入 S1–S9 错误预算）。
- **检测方式**：G-36 `make doctor` 的 migration 项（不是用户报障）。

## 时间线

| 时间（约） | 动作 | 结果 |
|---|---|---|
| 14:00 | `make doctor`（新实现的 7 项体检） | `[FAIL] migration 数据库版本 0001_initial != 代码 head 0002_tool_log_duration` |
| 14:02 | `alembic -c alembic.ini upgrade head` | `OperationalError (1060, "Duplicate column name 'duration_ms'")` |
| 14:04 | `SHOW COLUMNS FROM tool_logs LIKE 'duration_ms'` | 列已存在（FLOAT NULL），与 0002 的目标结构一致 |
| 14:06 | 备份确认（本地开发库，无写入变更）后 `alembic stamp 0002_tool_log_duration` | `Running stamp_revision 0001_initial -> 0002_tool_log_duration` |
| 14:08 | 再次 `make doctor` | `[PASS] migration 数据库版本 0002_tool_log_duration = head`，7 项全 PASS |

## 根因

G-16 之前，启动路径带有「缺列就 ALTER TABLE 补列」的兜底逻辑：它给 `tool_logs` 加了 `duration_ms`，但**没有写入 `alembic_version`**。G-16 删除兜底、改为 Alembic 单一来源后，旧库仍停留在 `0001_initial`，而列已经存在；于是 0002 的 `ADD COLUMN` 触发 1060。

这不是迁移脚本写错，而是**历史库的版本标记与实际 schema 不一致**（半迁移状态）。

## 止血与恢复

1. 只读核对：`alembic current`、`alembic heads`、`SHOW COLUMNS` 确认列类型与 0002 定义一致。
2. 确认没有其他未记录的 DDL 差异后，才执行 `alembic stamp 0002_tool_log_duration`。
3. 没有使用 `DROP COLUMN` 重跑迁移（会破坏数据），也没有在结构不一致时盲目 stamp。
4. 复检 `make doctor` 7 项全 PASS，`make check` 通过。

## 影响与数据

- 无数据丢失；未执行任何 DELETE/UPDATE/DROP。
- 迁移失败只影响「升级」动作，CLI 在 0001 schema 下仍可运行（0002 为 expand-only 可空列）。

## 回归与防再发

- `tests/test_migrations.py` 覆盖 upgrade→downgrade→upgrade 往返；`tests/test_schema_validation.py` 覆盖 schema 缺失/版本不符的报错。
- `make doctor` 把「DB 版本 != head」变成一条可执行检查；runbook 场景 4 固化了「先核对、再 stamp」的处置，明确禁止结构不一致时 stamp。
- 新库一律 `--migrate` 初始化；不再存在启动时自动 ALTER 的路径。

## 后续项

| 项 | Owner | 截止 |
|---|---|---|
| 在 release 检查单中加入 `make doctor`（打 tag 前） | ikun-ikun1 | 2026-11-15 |
| 评估 CI 增加「旧库升级」用例（当前只测空库往返） | ikun-ikun1 | 2026-11-30 |

## 证据

- `make doctor` 输出：migration FAIL → stamp → 7 PASS（见上方时间线）。
- 迁移定义：`migrations/versions/0002_tool_log_duration.py`（只加可空列）。
- 处置步骤：`docs/runbook.md` 场景 4。
