# AgentKernel 项目状态（单一事实源）

> 更新时间：2026-10-29 · 维护者：ikun-ikun1
> 本页只放「当前是什么状态」；标准与阈值见 [production-standard.md](./production-standard.md)，逐项差距见 [production-standard-gap.md](./production-standard-gap.md)。

## 1. 一眼结论

| 维度 | 状态 | 证据 |
|---|---|---|
| 定位 | Python CLI Agent Runtime 研究原型（面试作品），按可上生产的工程标准建设 | 边界见 [technical-scope-and-boundary.md](./technical-scope-and-boundary.md) |
| 测试 | **100 个测试**；本地 `95 passed / 5 skipped`（无 DSN），CI `100 passed / 0 skipped` | `pytest -q`；CI workflow 用 `grep SKIPPED` 强制 0 skip |
| 评测 | `python eval.py` → 5/5 | 本机实测 |
| 真实模型 | 7 次 live 调用（含 `make test-live` 冒烟），tokens/cost 非空；累计 < $0.001 | [reports/2026-W44.md](./reports/2026-W44.md) |
| CI | GitHub Actions 3 个 job：`test`（MySQL 8 service）、`eval-minimal`、`docker` | [CI](https://github.com/ikun-ikun1/AgentKernel/actions/workflows/ci.yml) |
| 镜像 | 多阶段、非 root（uid 10001）、310MB、体积门禁 <400MB | `make docker-smoke` |
| 数据层 | MySQL 8 为事实源；SQLite 仅测试适配器；Alembic 迁移 0001/0002 | `make check` + `test_migrations.py` |
| 观测 | JSONL 16 字段、trace/span 树、token/成本、`make report/trace/prune` | [production-standard.md §4.2](./production-standard.md) |

## 2. 测试与门禁

```bash
make check        # lint + format-check + mypy + pytest(排除 live) + eval(mock)
make report       # 从 JSONL 生成 SLO 周报（docs/reports/）
make trace        # 按 trace_id 打印 span 树
make prune        # 日志 14 天 / DB 90 天（支持 dry-run）
make test-live    # 真实 API 冒烟：1 次调用（需 AGENTKERNEL_LIVE_API=1 与 DEEPSEEK_API_KEY）
make docker-smoke # 构建镜像并跑启动 smoke（只证明能启动）
```

| 门禁 | 阈值（项目级） | 当前 |
|---|---|---|
| 可重复 | `uv.lock` + `.python-version` + `make sync` | ✅ 基础 / **PARTIAL**：镜像 digest（G-45/G-46）、默认口令（G-06）批二 |
| 可观测 | JSONL 16 字段 + span + 成本 + 周报 | ✅（缺 OTLP，G-47） |
| 可回滚 | 迁移 expand-only + downgrade 往返测试 | ✅ 迁移 / **PARTIAL**：备份与恢复演练（G-17/G-18）批二 |
| 可控制 | MCP profile 精确 argv + 文档根白名单 + env 白名单 | ✅ 基础 / **PARTIAL**：G-24 base_url allowlist、G-25 会话预算、G-27 工具结果隔离 批二 |
| 可验证 | 0 skip、迁移往返、真实 MySQL | ✅ 基础 / **PARTIAL**：G-30 覆盖率、G-32 golden set 50 条 批二 |
| 可运维 | runbook / doctor / 定期恢复演练 | ❌ 批二（G-35/G-36/G-17） |

## 3. 批一交付（P0-1 ~ P0-5）

| 项 | 内容 | 状态 |
|---|---|---|
| P0-1 | `uv.lock`、`.python-version`、`Makefile`、ruff I001 | ✅ 已合并 |
| P0-2 | GitHub Actions（MySQL service、0 skip 强制） | ✅ 已合并 |
| P0-3 | 多阶段 Dockerfile、非 root、体积门禁 | ✅ 已合并 |
| P0-4 | JSONL 日志、trace/turn、token/成本、写库脱敏 | ✅ 已合并 |
| P0-4b | span 树、`duration_ms` 迁移、prune、周报索引、真实 API 验证 | ✅ 已合并 |
| P0-5 | MCP profile、文档根 realpath、DSN 脱敏、MySQL 绑回环 | ✅ 已合并（PR #5） |

## 4. 未完成与风险（Top）

| # | 项 | 影响 | 计划 |
|---|---|---|---|
| 1 | 覆盖率工具与 80% 门槛（G-30） | 改坏关键路径无自动拦截 | 批二 |
| 2 | golden set 50 条（G-32） | S1/S2 统计意义不足 | 批二 |
| 3 | `DEEPSEEK_BASE_URL` 无 allowlist（G-24） | key 可能被改环境变量发往任意主机 | 批二 |
| 4 | 迁移/DDL 双轨收口（G-16） | `create_all` 与 Alembic 并存 | 批二 |
| 5 | MySQL/Python 基础镜像 digest（G-45/G-46） | tag 重推会静默变内容 | 待网络可达 |
| 6 | OTLP/外部看板（G-47） | 只有本地 JSONL | 接在线服务前 |
| 7 | runbook / 恢复演练（G-17/G-18/G-35） | 事故无步骤、备份未验证 | 批二 |
| 8 | 默认口令仍在代码里（G-06） | 弱口令可能被复制到真实部署 | 批二（小 PR） |

## 5. 文档地图

| 想知道什么 | 看哪里 |
|---|---|
| 现状与数字 | 本页 |
| 生产标准、SLO、门禁阈值 | [production-standard.md](./production-standard.md) |
| 逐项差距与优先级 | [production-standard-gap.md](./production-standard-gap.md) |
| 架构与数据流 | [architecture.png](./architecture.png) / [architecture.mmd](./architecture.mmd) |
| 项目背景与边界 | [project-background.md](./project-background.md) / [technical-scope-and-boundary.md](./technical-scope-and-boundary.md) |
| 数据库决策 | [Addendum/adr-001-mysql-primary-storage.md](./Addendum/adr-001-mysql-primary-storage.md) |
| 历史里程碑（2026-09） | [milestone-1](./milestone-1-kernel.md) / [milestone-2](./milestone-2-mcp.md) / [milestone-3](./milestone-3-deliverables.md) |

## 6. 复现命令

```bash
uv sync --frozen --extra dev --extra mysql --extra pdf
make check
AGENTKERNEL_MYSQL_TEST_DSN='mysql+pymysql://agentkernel:***@127.0.0.1:3306/agentkernel_test' \
  .venv/bin/python -m pytest -q      # 100 passed / 0 skipped
```
