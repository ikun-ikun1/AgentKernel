# ADR-002：跨进程会话写一致性（D4）

## 状态

Proposed（PR 1：设计与失败复现；实现见 PR 2）

## 背景

ADR-001 把 MySQL 8 设为主存储后，`MySQLRuntimeStore.append_message` / `log_tool_call` 用「进程内 per-session `threading.Lock` + 3 次有界重试」处理并发（提交 1597ec4）。这套机制只对**单进程多线程**有效：

- 两个 CLI 进程 / 一个 CLI + 一个 MCP 子进程同时写同一会话时，锁不共享；
- `sessions.updated_at` 由每个写事务各自计算后覆盖，最后提交者可能带着**更早**的时间戳，导致 `updated_at < max(messages.created_at)`；
- 20 并发下仍可能触发 1213 死锁 / 1205 锁等待，现有重试只有 3 次、间隔 0.05–0.1s。

D4 已确认「需要支持多进程 / 多客户端同时写同一会话」，因此当前实现判定为不达标（gap R10 高风险）。

## 选项对比

| 方案 | 机制 | 优点 | 缺点 | 结论 |
|---|---|---|---|---|
| **A. 行锁串行化** | 事务内 `SELECT id FROM sessions WHERE id=:id FOR UPDATE` → 再做 INSERT/UPDATE → COMMIT | 跨进程有效；无需新列/唯一约束；语义直观；回滚简单 | 同一会话写串行（可接受：CLI 场景单会话写入远低于 DB 能力）；要求会话行先存在 | **推荐** |
| B. 唯一约束 + 幂等键 | 消息加 `(session_id, idempotency_key)` 唯一索引，冲突则重试 | 允许并行写；天然去重 | 需要新列 + 迁移（且要先收口 G-16 双轨 DDL）；客户端必须生成稳定幂等键 | 备选（若未来要求高并发写） |
| C. 单写者队列 | 只有 writer 进程写，其他进程发消息 | 无锁竞争 | 需要额外进程/队列与故障转移；单机 CLI 过重 | 不采用 |

## 决策

采用 **A**，并保留进程内锁作为「减少同进程内无效竞争」的优化：

1. 写事务顺序固定：先锁 `sessions` 行（`FOR UPDATE`），再写 `messages` / `tool_logs`，最后 `UPDATE sessions.updated_at`；跨进程靠 InnoDB 行锁串行化。
2. `updated_at` 在拿到行锁**之后**取时间，保证它不早于本次写入的消息时间；最终 `updated_at == max(messages.created_at)`。
3. 重试仍保留：命中 1213/1205 时指数退避（0.05 → 0.1 → 0.2s，加抖动），最多 3 次；超过则抛出可读错误。
4. `_session_locks` 改为有界结构（LRU，上限如 1024），避免会话数增长导致内存无界。
5. 会话行必须先存在：`create_session` 幂等（`INSERT IGNORE`）；`append_message` 在锁行失败（无行）时报明确错误，而不是静默丢写。

## 影响

- 不改 schema → 不需要新迁移，回滚只是代码回滚（无数据形态变化）。
- 同一会话的写变为串行；跨会话写互不影响（行锁粒度是会话）。
- 若未来采用 B，需先完成 G-16（去掉 `create_all`，只走 Alembic）。

## 验证

- 新增 `tests/test_mysql_multiprocess.py`：**20 进程 × 20 次**写同一会话，断言
  1. 无进程异常退出；2. 消息数 = 400（无丢失/重复）；3. `sessions.updated_at == max(messages.created_at)`。
- PR 1 中该用例在当前实现上应为**失败**（用 `xfail(strict=True)` 记录，CI 保持绿）；PR 2 移除 xfail 并转绿。
- 线程级用例（`test_mysql_integration.py:85`）保留，但不再作为跨进程证据。

## 回滚

PR 2 可整体 revert：无 schema 变更，回滚后行为退化为「进程内锁 + 重试」，多进程一致性不再保证（与当前一致）。
