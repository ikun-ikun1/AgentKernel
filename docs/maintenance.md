# 维护手册（v0.5.0 冻结点）

> 适用版本：**v0.5.0**（2026-10-31）；包含 P0-1 审批写工具与 P0-2 真实评测。架构主线已收口；本文件说明支持边界、日常命令、依赖/ digest 更新、发版回滚与扩展点。
> 当前数字（测试数/覆盖率/CI）统一见 [status.md](./status.md)。

## 1. 支持范围与不承诺项

**支持：**

- Python 3.11 CLI；单机 MySQL 8（或 SQLite 测试适配器）；DeepSeek/OpenAI 兼容端点。
- canonical import 路径与 CLI 行为（参数、输出、退出码、JSONL 事件字段）。
- 迁移（Alembic）、备份/恢复演练、观测（JSONL/trace/report/可选 OTLP）、MCP profile 安全边界。
- 本地副作用写工具 `write_workspace_file`：工作区沙箱 + CLI y/N 审批（默认拒绝）+ 单进程幂等；审批审计以 JSONL `tool` 事件为准（`tool_logs` 表未加审批列，无 schema 迁移）。

**不承诺：**

- 多租户、Web 平台、在线服务 SLA、7×24 on-call；
- 高并发/分布式部署；跨地区容灾；
- 第三方 MCP server 的行为与安全（只保证启动边界）；
- 跨进程持久化幂等（P0-1 只做单进程；无 schema 迁移）；
- 旧 import shim（v0.4.0 已删除，见 [migration-shims.md](./migration-shims.md)）。

## 2. 冻结的公共面

- **CLI**：`python -m agentkernel` 的参数、退出码、交互命令（`/new /sessions /history /ingest /docs /logs /help /quit`）。
- **入口**：`python -m agentkernel.mcp_server`；旧的 `agentkernel.mcp.server` 已删除。
- **import 路径**：`ports/*`、`adapters/*`、`application/*`、`rag/{knowledge,models,loaders,chunking,indexes}`、`protocol/mcp_framing`、`observability/events`。
- **事件字段**：JSONL turn/tool 字段表与 OTLP 字段语义（见 `utils/observability.py`、`observability/events.py`）；审批工具额外带 decision/reviewer/key/summary/timestamp（兼容别名 approval_*），幂等命中带 `deduplicated`。
- **版本**：semver tag；v0.4.0 为 Breaking（删除 shim），之后不再新增架构层。

## 3. 日常命令

```bash
make check          # ruff + format + mypy + pytest + mock eval；提交前必跑
make doctor         # 7 项体检（python/.env/依赖/MySQL/迁移/口令/磁盘）
make backup         # 迁移/打 tag 前备份
make restore-drill  # 恢复到临时库并校验行数（月度/季度）
make report         # SLO 周报（JSONL → docs/reports/）
make eval-live-p02  # P0-2 24 条真实任务（成本上限 $1，产出 JSON/MD）
make bench          # 启动/单轮 ReAct/MCP/SQLite/MySQL 延迟基线（DSN 可选）
make security       # gitleaks + semgrep（发布前）
make audit          # pip-audit（需网络）
make docker-build / docker-smoke / docker-size
```

> 本地无 MySQL 时：`make test` 会跳过 DSN 用例；CI 用 service container 强制 0 skip。

## 4. 依赖与镜像 digest 更新

- **Dependabot**：Docker 镜像每周、GitHub Actions 每月（`.github/dependabot.yml`）。
- **digest-check**：每周一比对 docker.io 的 `mysql:8.0.46` / `python:3.11.15-slim` 与四处 pin（Dockerfile / Makefile / compose python / compose mysql），漂移会开 issue 并失败提醒（`.github/workflows/digest-check.yml`）。
- 手工更新顺序：改 `Dockerfile` → `Makefile` → `docker-compose.yml` → 更新 G-45/G-46 证据 → 跑 `make check` + CI docker job。
- digest 必须来自 **docker.io**；镜像站镜像即使 digest 相同，也不能把镜像站 digest 当来源。当前 compose 的 mirror host + docker.io digest 已验证可拉取。

## 5. 发版与回滚

1. 更新 `pyproject.toml` / `src/agentkernel/__init__.py` / `uv.lock` 版本；
2. 更新 `CHANGELOG.md`（Breaking 必须标出）；
3. `uv build` 产 wheel/sdist，干净 venv 安装 + CLI smoke；
4. `make check` + CI 全绿；打 annotated tag `vX.Y.Z` 并推送；
5. 发版后 24h 内跑一次 `make eval`；记录 S4/S8 数据。

回滚：切到上一个 tag → `uv sync --frozen` → 恢复最近备份（如涉及数据）。v0.4.0 的回滚锚点可用 `v0.3.1`（仍含 shim）或 `v0.2.0`。

## 6. 扩展点（只允许加适配器，不改核心边界）

| 端口 | 位置 | 允许的扩展 |
|---|---|---|
| `LLMClient` | `ports/llm.py` | 新增供应商适配器（OpenAI-compatible 之外）；不把 SDK 类型带进 `runtime/agent.py` |
| `RuntimeStore` | `ports/runtime_store.py` | 新存储适配器；D4 行锁语义必须保持，多进程用例必须绿 |
| `MCPTransport` | `ports/mcp_transport.py` | 新 transport；profile 精确 argv/env 白名单边界不变 |
| 审批回调 | `Agent.approval_fn`（`application/tool_executor.ApprovalFn`） | 只对 `requires_approval` 工具生效；不读全局 env，不在 Registry 里依赖 CLI |

**不要做**：新增 architecture layer、DI 容器、async 重写、微服务拆分；不要为了目录好看移动已冻结的 canonical 路径。

## 7. 季度检查清单

- [ ] `make doctor` 7/0
- [ ] `make restore-drill` PASS（RPO/RTO 记录）
- [ ] `make security` 0 高危；依赖 audit 无未处理高危
- [ ] digest-check 无漂移；Dependabot PR 已处理
- [ ] `make check` + CI 绿；覆盖率不低于 80%

## 8. 相关文档

- 事故处置：[runbook.md](./runbook.md)（6 场景 + 模板）
- 当前状态：[status.md](./status.md)
- 性能基线快照：[reports/bench-20261030.md](./reports/bench-20261030.md)
- 旧路径迁移：[migration-shims.md](./migration-shims.md)
- 架构决策：[ADR-003](./Addendum/adr-003-production-architecture.md)
