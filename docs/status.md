# AgentKernel 项目状态（单一事实源）

> 更新时间：2026-10-30 · 维护者：ikun-ikun1
> 本页只放「当前是什么状态」；标准与阈值见 [production-standard.md](./production-standard.md)，逐项差距见 [production-standard-gap.md](./production-standard-gap.md)。

## 1. 一眼结论

| 维度 | 状态 | 证据 |
|---|---|---|
| 定位 | Python CLI Agent Runtime 研究原型（面试作品），按可上生产的工程标准建设 | 边界见 [technical-scope-and-boundary.md](./technical-scope-and-boundary.md) |
| 架构 | A0–A6 + A7.1 LLM 端口注入 + A7.2 Agent 拆分（184 行 facade；ReAct/context/tool 已外移）；A7.3–A7.4 待做 | [ADR-003](./Addendum/adr-003-production-architecture.md) |
| 测试 | **190 个测试**；本地 `184 passed / 6 skipped`（无 DSN），CI `189 passed / 1 deselected`（live）/ `0 skipped`；覆盖率 **83%**（CI 门槛 80%） | `pytest -q`；CI workflow 用 `grep SKIPPED` 强制 0 skip |
| 评测 | `make eval` → **50/50**（mock golden set，5 类 ×10）；`make eval-live` 20 条真实调用数据就绪 | 本机实测 |
| 真实模型 | 8 次 live 调用（含 `make test-live` 冒烟，allowlist 生效后复测通过），tokens/cost 非空；累计 < $0.001 | [reports/2026-W44.md](./reports/2026-W44.md) |
| CI | GitHub Actions 4 个 job：`test`（MySQL 8 service）、`eval-minimal`、`security`（gitleaks/semgrep/pip-audit）、`docker` | [CI](https://github.com/ikun-ikun1/AgentKernel/actions/workflows/ci.yml) |
| 镜像 | 多阶段、非 root（uid 10001）、310MB、体积门禁 <400MB | `make docker-smoke` |
| 数据层 | MySQL 8 为事实源；SQLite 仅测试适配器；Alembic 迁移 0001/0002 | `make check` + `test_migrations.py` |
| 观测 | JSONL 16 字段、trace/span 树、token/成本、`make report/trace/prune` | [production-standard.md §4.2](./production-standard.md) |

## 2. 测试与门禁

```bash
make check        # lint + format-check + mypy + pytest(排除 live) + eval(50 条 mock)
make report       # 从 JSONL 生成 SLO 周报（docs/reports/）
make trace        # 按 trace_id 打印 span 树
make prune        # 日志 14 天 / DB 90 天（支持 dry-run）
make test-live    # 真实 API 冒烟：1 次调用（需 AGENTKERNEL_LIVE_API=1 与 DEEPSEEK_API_KEY）
make security     # gitleaks + semgrep（离线）
make coverage     # 覆盖率报告；有 DSN 时自动 --cov-fail-under=80（CI 门槛）
make eval-live    # golden set 20 条真实调用（需 DEEPSEEK_API_KEY）
make audit        # pip-audit 审计 lock 依赖（需网络）
make docker-smoke # 构建镜像并跑启动 smoke（只证明能启动）
```

| 门禁 | 阈值（项目级） | 当前 |
|---|---|---|
| 可重复 | `uv.lock` + `.python-version` + `make sync` | ✅ 基础 / **PARTIAL**：镜像 digest（G-45/G-46）待补；默认口令已清理（G-06） |
| 可观测 | JSONL 16 字段 + span + 成本 + 周报 + OTLP | ✅ 可选 OTLP/HTTP 导出（`OTEL_EXPORTER_OTLP_ENDPOINT`，本地假 collector 测试）；周报仍手动 |
| 可回滚 | 迁移 expand-only + downgrade 往返 + 备份/恢复演练 + tag/wheel | ✅ `v0.2.0` tag + wheel（干净 venv 安装/CLI smoke EXIT=0）；`make backup` / `make restore-drill` 最新演练 PASS（报告见 [reports/restore-drill-20261029.md](./reports/restore-drill-20261029.md)） |
| 可控制 | MCP profile 精确 argv + 文档根白名单 + env 白名单 + 会话预算 | ✅ 会话预算（单会话 150k tokens / 单轮 5 次工具调用，`budget_exceeded` 事件）已落地，G-24/G-25/G-27 完成 |
| 可验证 | 0 skip、迁移往返、真实 MySQL、覆盖率 83% + 80%、golden set 50、三类扫描、fuzz 语料 | ✅ 500 条坏 JSON + 100 条非法帧（0 崩溃/0 挂起），G-33 完成 |
| 可运维 | runbook / doctor / 定期恢复演练 | ✅ runbook 6 场景 + `make doctor` 7 项 + [CHANGELOG](../CHANGELOG.md) + `v0.2.0` tag + [首次事故复盘](./reports/incident-20261030-schema-drift.md) |

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
| 1 | MySQL/Python 基础镜像 digest（G-45/G-46） | tag 重推会静默变内容 | 待网络可达 |
| 2 | A7.3–A7.4：端口取舍/架构图/v0.3.0 | 核心拆分已完成，端口与发布收口未完成 | 继续 A7 |

## 5. 文档地图

| 想知道什么 | 看哪里 |
|---|---|
| 现状与数字 | 本页 |
| 生产标准、SLO、门禁阈值 | [production-standard.md](./production-standard.md) |
| 逐项差距与优先级 | [production-standard-gap.md](./production-standard-gap.md) |
| 架构与数据流 | [architecture.png](./architecture.png) / [architecture.mmd](./architecture.mmd) |
| 生产问题叙事 | [production-problems.md](./production-problems.md) |
| 架构目标与重构 ADR | [Addendum/adr-003-production-architecture.md](./Addendum/adr-003-production-architecture.md) |
| 项目背景与边界 | [project-background.md](./project-background.md) / [technical-scope-and-boundary.md](./technical-scope-and-boundary.md) |
| 数据库决策 | [Addendum/adr-001-mysql-primary-storage.md](./Addendum/adr-001-mysql-primary-storage.md) |
| 事故处置与复盘 | [runbook.md](./runbook.md) / [首次复盘](./reports/incident-20261030-schema-drift.md) |
| 变更记录 | [CHANGELOG.md](../CHANGELOG.md) |
| 历史里程碑（2026-09） | [milestone-1](./milestone-1-kernel.md) / [milestone-2](./milestone-2-mcp.md) / [milestone-3](./milestone-3-deliverables.md) |

## 6. 复现命令

```bash
uv sync --frozen --extra dev --extra mysql --extra pdf
make check
AGENTKERNEL_MYSQL_TEST_DSN='mysql+pymysql://agentkernel:***@127.0.0.1:3306/agentkernel_test' \
  .venv/bin/python -m pytest -q      # 167 passed / 1 deselected（live）/ 0 skipped；覆盖率 82.89%（CI，含 MySQL 集成）
```
