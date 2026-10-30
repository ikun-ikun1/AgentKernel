# AgentKernel Runbook（6 个事故场景）

> 适用：单用户 CLI / 单机 MySQL 的本地与演示环境。目标不是「讲原理」，而是**凌晨也能照着做**：先判定，再止血，再恢复，最后留证据。
> 关联：[production-standard.md](./production-standard.md)（SLO/错误预算）、[status.md](./status.md)（当前数字）、[production-standard-gap.md](./production-standard-gap.md)（G-35/G-36）。

## 0. 通用原则（每个场景都先做）

1. **先体检，再看日志**：`make doctor` 输出 7 项（python / .env / 依赖 / MySQL / 迁移 / 默认口令 / 磁盘），先排除环境问题。
2. **保留现场**：不要删 `~/.agentkernel/logs/agentkernel.jsonl`、不要重启 MySQL 容器、不要清空库；先复制日志与 `docker compose logs`。
3. **敏感信息**：DSN、API Key 一律脱敏后再贴到 issue/聊天；`make doctor` 与 `--migrate` 输出已对 DSN 打码。
4. **破坏性操作前备份**：`make backup`；恢复演练用 `make restore-drill`，不要直接对生产库跑 restore。
5. **SLO 冻结**：若错误预算已耗尽（见 standard §2.2），只允许修复动作，不做功能发布。
6. **记录**：事故结束后在 `docs/reports/` 留一份 `incident-YYYYMMDD.md`（时间线、影响、根因、动作、后续项），并把新发现补进本文件。

---

## 1. 启动失败（依赖缺失 / 配置错误 / DSN 未设置）

**典型现象**

- `ModuleNotFoundError: No module named 'openai'` / `pymysql`
- `缺少 Runtime 存储 DSN：请设置 AGENTKERNEL_DB_URL...`
- `配置错误：DEEPSEEK_BASE_URL 的主机不在允许列表`
- 进程启动即退，退出码 2。

**判定**

```bash
make doctor                      # 看 deps / env / python 三项
python -m agentkernel --db sqlite:///:memory: --kb-db :memory: --kb-backend lexical
```

- `deps` FAIL → 依赖没装全；`env` WARN → 没有 `.env`（可用环境变量代替）。
- 只报 DSN → 没配 `AGENTKERNEL_DB_URL`，且没传 `--db`。
- 报 allowlist → `DEEPSEEK_BASE_URL` 指向了非白名单主机（见 `utils/env.py`）。

**止血**

- 依赖：`make sync`（lock 安装）；本地全量功能用 `make sync-all`。
- DSN：`cp .env.example .env && chmod 600 .env`，填真实 DSN；或临时 `--db sqlite:///:memory:` 验证 CLI 本身。
- allowlist：改回 `https://api.deepseek.com`；确需自建端点时显式设置 `AGENTKERNEL_ALLOWED_LLM_HOSTS`（只加可信主机）。

**恢复与验证**

```bash
make doctor
printf '/quit\n' | python -m agentkernel --db sqlite:///:memory: --kb-db :memory: --kb-backend lexical
make test
```

**回滚**：恢复上一版 `.env`（`cp .env.bak .env`，权限 600）与上一版依赖（`git checkout -- uv.lock && make sync`）。
**升级条件**：同一错误在 24h 内重复出现，或需要改代码才能启动。

---

## 2. MySQL 不可用（连接拒绝 / 超时 / 认证失败）

**典型现象**

- `Runtime 存储初始化失败：OperationalError ... (2003, "Can't connect to MySQL server")`
- `(1045, "Access denied for user ...")`
- `(2005, "Unknown MySQL server host")`；CLI 启动卡住后退出。

**判定**

```bash
make doctor                                   # mysql 项 FAIL/WARN + 迁移项
docker compose ps                             # mysql 是否 healthy
docker compose logs --tail=100 mysql
mysqladmin -h 127.0.0.1 -P 3306 ping          # 需要本机客户端
```

- 连接拒绝 → 容器没起/端口没映射/防火墙。
- 认证失败 → `.env` 的 `MYSQL_PASSWORD` 与 DSN 不一致，或用了旧卷里的旧口令。
- 主机名错误 → `127.0.0.1` vs `mysql`（容器内）混淆。

**止血**

```bash
docker compose up -d mysql
docker compose ps
# 确认端口；不要把 3306 暴露到 0.0.0.0（见 docker-compose.yml 的回环绑定）
```

认证失败时：先用 `docker compose exec mysql mysql -uroot -p` 验证 root 口令；**不要**直接改数据卷里的用户表。开发环境可重建卷（**会丢本地数据**，先 `make backup`）：

```bash
make backup
docker compose down
docker compose up -d mysql
python -m agentkernel --migrate --db "$AGENTKERNEL_DB_URL"
make restore-drill
```

**恢复与验证**

```bash
make doctor                      # mysql + migration 必须 PASS
make test                        # MySQL 集成用例
make eval                        # mock golden 50
```

**回滚**：若刚改过 `.env`/compose，回退到上一版并重启；数据损坏时按 `docs/reports/restore-drill-*.md` 的步骤从最新备份恢复。
**升级条件**：数据文件损坏、需要 PITR、或 15 分钟内无法恢复服务。

---

## 3. API Key 无效 / 出站被拒 / 429 或 5xx

**典型现象**

- `AuthenticationError: 401` / `Invalid API key`
- `LLMConfigError: DEEPSEEK_BASE_URL 必须使用 https...`
- `RateLimitError: 429`；`APIConnectionError` / `APITimeoutError`
- CLI 回复 `[AgentKernel 错误] ...`。

**判定**

```bash
make doctor
grep -c '^DEEPSEEK_API_KEY=' .env          # 只看是否存在，不打印值
python - <<'PY'
from agentkernel.utils import env
env.load_env()
print("host ok:", env.validate_base_url())
print("key set:", bool(env.get_api_key()))
PY
```

再做一次最小真实调用（会花钱，单次）：

```bash
AGENTKERNEL_LIVE_API=1 python -m pytest -q -m live
```

- 401/403 → key 失效/被撤销/额度耗尽；到控制台换 key。
- allowlist/LLMConfigError → 端点配置错误（不要用 `http://` 访问公网）。
- 429 → 触发限流；429/5xx 由 client 重试（默认 2 次，超时 60s），仍失败则停止重试，避免放大成本。
- 超时 → 网络/DNS；先 `curl -I https://api.deepseek.com` 验证出网。

**止血**

- 换 key：更新 `.env`（600）后重启 CLI；**不要把 key 提交到 git**。
- 临时降级：`DEEPSEEK_MODEL` 换可用模型；或离线跑 mock：`make eval`（不需要 key）。
- 成本保护：`AGENTKERNEL_MAX_SESSION_TOKENS` 调低（如 50000）；停止 live eval。

**恢复与验证**

```bash
AGENTKERNEL_LIVE_API=1 python -m pytest -q -m live
make eval                        # 50/50 mock 必须全过
```

**回滚**：恢复旧 key（若新 key 也被限流）；把 `DEEPSEEK_MODEL` 改回上一版。
**升级条件**：key 疑似泄露（立即撤销 + `make security` 扫历史）、或账单异常增长。

---

## 4. 迁移失败 / schema 版本不符

**典型现象**

- `alembic.util.exc.CommandError` / `OperationalError (1060, "Duplicate column name 'duration_ms'")`
- 启动报 `schema 版本不匹配` / `缺少 alembic_version` / `缺少表`
- `make doctor` 的 `migration` 项 FAIL：数据库版本 != 代码 head。

**判定（只读）**

```bash
make doctor
set -a; source .env; set +a
alembic -c alembic.ini current
alembic -c alembic.ini heads
python - <<'PY'
import os
from sqlalchemy import create_engine
from agentkernel.utils import env
env.load_env()
with create_engine(os.environ["AGENTKERNEL_DB_URL"]).connect() as c:
    print("version:", c.exec_driver_sql("SELECT version_num FROM alembic_version").fetchall())
    print("duration_ms:", c.exec_driver_sql("SHOW COLUMNS FROM tool_logs LIKE 'duration_ms'").fetchall())
PY
```

**止血 / 修复（按顺序，不要跳步）**

1. **先备份**：`make backup`。
2. 若 `alembic current` 落后，且对应列/表**不存在**：正常升级

   ```bash
   python -m agentkernel --migrate --db "$AGENTKERNEL_DB_URL"
   ```

3. 若列/表**已存在**（历史手工 ALTER 或旧版本留下的半迁移），`upgrade` 会报 1060。此时**只读核对结构完全一致**后，才允许 stamp：

   ```bash
   # 例：0002 只加 tool_logs.duration_ms FLOAT NULL
   SHOW COLUMNS FROM tool_logs LIKE 'duration_ms';   # 必须存在且类型一致
   alembic -c alembic.ini stamp 0002_tool_log_duration
   ```

   **禁止**在结构不一致时 stamp（会把坏 schema 标记成“已迁移”，后续迁移全部错位）。
4. 若 `alembic_version` 表丢失：先确认 schema 是否完整；空库直接 `upgrade head`；有数据的老库按 `0001_initial` 的表结构人工核对，再 stamp 到实际版本。

**验证**

```bash
make doctor                      # migration PASS: 0002 = head
python -m pytest -q tests/test_migrations.py tests/test_schema_validation.py
make test
```

**回滚**：迁移是 expand-only；回滚代码而不是回滚列。必须降级时先在临时库演练 `alembic downgrade -1`（0001 的 downgrade 会先删子表，见迁移脚本），并确认已备份。
**升级条件**：迁移脚本本身有缺陷（需要改代码）、或数据修复需要 DBA 介入。

---

## 5. 死锁 / 跨进程写同一会话

**典型现象**

- `OperationalError (1213, "Deadlock found when trying to get lock")`
- 两个 CLI 同时写同一 session 时，偶发 `Lock wait timeout exceeded`
- 消息重复/丢失；工具日志数量对不上。

**判定**

```bash
make test                                        # 含多进程用例
python -m pytest -q tests/test_mysql_multiprocess.py -v
python - <<'PY'
import os
from sqlalchemy import create_engine
from agentkernel.utils import env
env.load_env()
with create_engine(os.environ["AGENTKERNEL_DB_URL"]).connect() as c:
    row = c.exec_driver_sql("SHOW ENGINE INNODB STATUS").fetchone()
    print(str(row[2])[-4000:])  # LATEST DETECTED DEADLOCK 在末尾
PY
```

- `test_mysql_multiprocess` 失败 → 先看是死锁逃逸、还是断言行数不一致。
- `INNODB STATUS` 的 `LATEST DETECTED DEADLOCK` 会给出两条事务的 SQL 与锁等待。

**止血**

- 停止并发写入（只留一个 CLI 会话），避免重试风暴。
- 确认代码路径：同一会话写应走 `SELECT ... FOR UPDATE` 行锁 + 有界 LRU 进程内锁 + 指数退避（见 `memory/mysql_store.py`、ADR-002）；重试次数用尽后必须显式报错，不能静默丢消息。
- 不要用 `KILL` 连接作为常规手段；只在确认长事务阻塞时处理。

**恢复与验证**

```bash
python -m pytest -q tests/test_mysql_multiprocess.py
python -m pytest -q tests/test_memory.py
make doctor
```

复现脚本（本地安全）：开两个终端各跑同一 session 的写入，或直接跑上面的多进程用例；记录失败率与耗时，附在事故报告里。

**回滚**：回退到上一版写入路径（`git revert` 对应提交）；若数据已不一致，按备份恢复并重放可确认的消息。
**升级条件**：死锁可稳定复现且重试无法收敛，或出现数据丢失。

---

## 6. 检索退化为纯词法（向量后端不可用）

**典型现象**

- 启动提示 `知识库提示：... 降级为 lexical`
- `--kb-backend semantic/hybrid` 启动失败或很慢（模型下载/Chroma 不可用）
- 回答引用命中率下降；S6 的 Recall@5 低于 0.85。

**判定**

```bash
python -m agentkernel --kb-backend lexical ...    # 显式词法，确认主流程可用
python -m pytest -q tests/test_rag.py -v
python -m pytest -q -k "rag or retrieval"
```

- 依赖缺失（chromadb/sentence-transformers）→ `make sync-all` 或保持 lexical。
- 模型下载失败/磁盘满 → 看 `make doctor` 的 disk 项与 HF 缓存目录。
- MySQL 全文索引缺失 → `make doctor` 的 migration 项；`idx_chunks_ft` 由迁移创建。

**止血**

- 显式降级：`--kb-backend lexical`（默认即为 lexical，稳定优先）。
- 知识库存储临时切 SQLite：`--kb-db /tmp/agentkernel-kb --kb-backend lexical`。
- 不删除已有 MySQL 知识库数据；只切换读路径。

**恢复与验证**

```bash
make doctor
make test
make eval
# 有 golden 查询时：对比降级前后 Recall@5（S6 门槛 0.85）
```

**回滚**：恢复 `AGENTKERNEL_KB_DSN` 与 `--kb-backend` 原值；如刚重建过索引，按备份恢复知识库表。
**升级条件**：Recall@5 连续两次低于 0.85，或降级后主流程仍不可用。

---

## 附：事故记录模板（复制到 `docs/reports/incident-YYYYMMDD.md`）

```markdown
# Incident YYYY-MM-DD：<一句话>

- 发现时间 / 恢复时间 / 影响时长：
- 影响面：<命令、会话、数据、成本>
- SLO：<S1..S9 哪项、是否消耗错误预算>
- 时间线：<hh:mm 动作与结果>
- 根因：
- 止血动作：
- 恢复验证：<make doctor / make test / make eval 输出摘要>
- 回滚点：<commit/tag/备份文件>
- 后续项：<owner + 截止日>
```
