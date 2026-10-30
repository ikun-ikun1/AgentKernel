# AgentKernel 生产标准差距分析

> 对照文件：`docs/production-standard.md`（v0.1 草案）
> 分析日期：2026-10-29
> 基线版本：`~/ai-production/baseline` v1.0
> 结论口径：**PASS** = 有证据满足；**PARTIAL** = 部分满足且有残余风险；**FAIL** = 无证据或明显不满足。
> 全部证据均可复现，见文末「复现命令」。

---

## 0. 六门禁总览

| # | 门禁 | 结论 | 一句话理由 | 阻断项 |
|---|---|---|---|---|
| 1 | 可重复 | **PARTIAL** | 锁文件/解释器/`make check`/CI/格式化门禁已就绪；仍缺镜像 digest（G-04/G-45/G-46）与默认口令清理（G-06） | G-04, G-06, G-45, G-46 |
| 2 | 可观测 | **PARTIAL（接近完成）** | 已实现 JSONL 字段表、trace/span 树、token/成本与定价版本、写库脱敏、审计失败可见、`duration_ms` 落库、`make report` + 索引、`make prune`；仍缺 OTLP 导出与定时调度 | G-07…G-13、G-47 |
| 3 | 可回滚 | **PARTIAL** | 0001 迁移有对称 downgrade；但无迁移测试、无备份/恢复演练、DDL 双轨（启动 `create_all`）、无 tag/wheel | G-14…G-19 |
| 4 | 可控制 | **PARTIAL** | 工具白名单、无 shell/eval、AST 计算器、只读 KB 已达标；但外部 MCP 任意命令继承 key、`/ingest` 无根目录、无 token 预算、base_url 无 allowlist | G-20…G-27 |
| 5 | 可验证 | **PARTIAL** | CI 已全绿（113 passed / 0 skipped）+ mypy 全绿 + eval 5/5；但覆盖率不可测、golden set 仅 5 条、无 fuzz/扫描 | G-30…G-34 |
| 6 | 可运维 | **PARTIAL** | 有 ADR、有降级路径；但无 runbook、无 `make doctor`、无 SLO 周报、无事故模板、无 CHANGELOG/tag | G-35…G-40 |

> 说明：`PARTIAL` 不等于「差不多可以上线」，只表示该门禁已有可复用的实现或文档，缺的是证据链与自动化。

---

## 1. 可重复（Reproducible）

| # | 标准要求（§4.1） | 现状 | 证据 | 风险 | 优先级 | 验收标准 |
|---|---|---|---|---|---|---|
| G-01 | 提交 `uv.lock`，`uv sync --frozen` | ✅ **已实现** | `uv.lock`（158 包）；CI `uv lock --check` + `uv sync --frozen`；PR #1 干净 runner 首次全绿 | — | — | 空环境 `uv sync --frozen` 成功且 pytest 全绿（CI 已证） |
| G-02 | 解释器固定 + `.python-version` | ✅ **已实现** | `.python-version`=`3.11.15`；CI `setup-uv` 读取该文件；README/status 注明 | — | — | 保持 |
| G-03 | 依赖必须可重建 | ✅ **已实现** | 干净 runner 由 `uv sync --frozen` 建环境（CI 三次全绿：PR #1/#2/#5） | — | — | 保持 |
| G-04 | MySQL 镜像固定 digest | ⚠️ **部分**：已从浮动 `8.0` 改为精确 `8.0.46`（compose + CI），**digest 未固定** | `docker-compose.yml`、`.github/workflows/ci.yml`；本机无法访问 `registry-1.docker.io` | 中：上游重推 tag 会静默变内容 | **P0（短）** | 两处改 `image@sha256:...`（并入 G-45） |
| G-05 | `make check` 单入口且 0 退出 | ✅ **已实现** | `Makefile`（sync/check/report/trace/prune/docker-*）；`make check` EXIT=0；CI 三个 job 复用同一入口 | — | — | 保持 |
| G-06 | 代码中不得有真实默认口令 | ❌ **仍未处理**：`factory.py` 的 `DEFAULT_MYSQL_DSN` 与 `alembic.ini` 仍是 `agentkernel:agentkernel` | `src/agentkernel/memory/factory.py:21`；`alembic.ini:5`；`tests/test_mysql_integration.py:5`（文档示例） | 中：默认弱口令会被复制到真实部署 | **P0（批二）** | 两处改为「必须由环境变量提供，否则报错」；`grep -r agentkernel:agentkernel` 为空 |
| G-42 | 应用镜像：多阶段、非 root、可构建（D1 新增） | **本地已实现并验证**（CI build job 待首次运行） | `Dockerfile` 多阶段，基础镜像 `python:3.11.15-slim`（Debian trixie）；`docker images` **310MB**（未压缩），`inspect .Size` **69MB**（压缩层）；`id -u` → `10001`；smoke `printf '/quit\n' \| docker run -i --rm agentkernel:local python -m agentkernel --db :memory: --kb-db :memory: --kb-backend lexical` → EXIT=0 + 启动横幅；镜像内 `chromadb` 不可导入（rag 未装）、`/app` 无 `.env`；`docker compose --profile app config` 通过（app 不默认启动） | 低：本地 build 用 daocloud 镜像源（`--build-arg`），CI 用 docker.io，默认路径由 CI 首次 build 证明；体积门禁用 `docker images` 口径（inspect 是压缩层，不能混用） | **P0（收尾）** | CI `docker` job 首次绿（含 <400MB 门禁）；smoke 只宣称「能启动」，不宣称 MySQL/运行态已验证 |
| G-46 | Python 基础镜像未 pin digest（P0-3 新增） | 已从浮动 `python:3.11-slim` 改为精确 `python:3.11.15-slim`，**仍无 digest** | `Dockerfile` `ARG PYTHON_IMAGE=python:3.11.15-slim`；`Makefile` `DOCKER_BASE` 同值；本机无法访问 `registry-1.docker.io` | 中：上游重推 tag 会静默改变基础镜像内容 | **P0（短）** | 改为 `python:3.11.15-slim@sha256:...`；digest 必须在 docker.io 侧取得（daocloud 的 digest 不能直接信任） |
| G-47 | OTLP/外部看板未接（P0-4b 遗留） | 只有本地 JSONL + `make trace`/`make report`；无 OTLP exporter、无 Prometheus/Grafana | `scripts/trace.py`、`scripts/report.py`；`pyproject.toml` 无 opentelemetry 依赖 | 低：单机 CLI 够用；接在线服务前必须补 | P2 | 需要时加 `opentelemetry-sdk`（可选 extra）+ `OTEL_EXPORTER_OTLP_ENDPOINT` 开关，并用本地假 collector 验证 |
| G-45 | MySQL 镜像未固定 digest（P0-2 引入的临时状态） | 两处已统一为精确 tag `8.0.46`，**仍无 digest** | `.github/workflows/ci.yml` service image `mysql:8.0.46`；`docker-compose.yml:3` `docker.m.daocloud.io/library/mysql:8.0.46`；本机无法访问 `registry-1.docker.io` 取 digest | 中：上游重推 tag 会静默改变行为 | **P0（短）** | 两处都改成 `image@sha256:...`，并在 CI 里验证可拉取 |
| G-43 | 格式化门禁 | ✅ **已实现** | `style` 提交（32 文件，AST 等价校验）+ `format --check` 进入 `make check`/CI；`.git-blame-ignore-revs` 已加 | — | — | 保持 |

---

## 2. 可观测（Observable）

| # | 标准要求（§4.2） | 现状 | 证据 | 风险 | 优先级 | 验收标准 |
|---|---|---|---|---|---|---|
| G-07 | 结构化 JSONL 日志 | ✅ **已实现** | `src/agentkernel/utils/observability.py`（JsonlFormatter/emit）；`runtime/agent.py` 每轮 1 条 `turn`、每次工具 1 条 `tool`；`tests/test_observability.py` 9 例 | — | — | 14 字段（12 核心 + 2 条件）由测试断言；日志默认 stderr，`AGENTKERNEL_LOG` 可落文件 |
| G-08 | `trace_id` 贯穿 LLM→工具→DB | ✅ **已实现** | `agent.run` 生成 trace_id/turn_id，`tool` 与 `turn` 事件共享（`tests/test_observability.py` 断言）；`session_id` 只以 12 位 sha256 出现 | — | — | 跨进程/OTLP span 仍属批二 |
| G-09 | token / 成本记账 | ✅ **已实现** | `runtime/llm.py` 用 ContextVar 捕获 usage（`pop_usage()`，chat 签名不变）；`observability.PRICING_TABLE_VERSION=2026-10-29`；未知模型 `cost_usd=null` + 单次 `pricing_unknown` 告警（有测试） | — | — | mock/假 LLM 下 tokens/cost 为 null 是预期，只有 live 调用才有真实 usage |
| G-10 | 指标（计数器/直方图） | ⚠️ **部分**：`make report` 聚合成功率/p50/p95/tokens/成本并维护索引；`make trace` 输出 span 树；无 Prometheus/OTLP 导出 | `scripts/report.py`、`scripts/trace.py`、`docs/reports/index.md` | 中：S4 可回归，但没有外部看板与告警联动 | P1 | 需要时接 OTLP 导出（G-47）；当前以周报 + trace 树代替 |
| G-11 | 工具耗时落库 | ✅ **已实现** | 迁移 `0002_tool_log_duration`（只加可空列，可回滚）；`sqlite_store` 老库自动补列；`mysql_store` 写库带 `duration_ms`；`/logs` 显示耗时；测试 `test_duration_roundtrip` | — | — | 迁移往返由 `tests/test_migrations.py` 在 CI（有 DSN）验证 |
| G-12 | 审计失败可见 | ✅ **已实现** | `agent.audit_failures` 计数 + `audit_failed` 事件（`runtime/agent.py`）；测试 `test_audit_failure_is_visible` | — | — | 主流程仍不因审计失败中断（按设计） |
| G-13 | 日志/DB 脱敏与截断 | ✅ **已实现（写库与日志字段）** | `observability.redact/truncate`；写库前都过一遍；`scripts/prune.py` + `make prune`（`LOG_DAYS=14`/`DB_DAYS=90`，支持 dry-run） | 低：`/history` 仍按设计展示消息正文；prune 需 cron/手工触发 | — | 自动调度留给运维侧；不阻塞门禁 |

---

## 3. 可回滚（Rollback）

| # | 标准要求（§4.3） | 现状 | 证据 | 风险 | 优先级 | 验收标准 |
|---|---|---|---|---|---|---|
| G-14 | 迁移必须有 downgrade | ✅ 0001 有对称 downgrade | `migrations/versions/0001_initial.py:78-88` 反序删表/索引 | — | — | 保持；新增迁移同规则 |
| G-15 | 迁移往返测试 | ✅ **已实现**（本地无 DSN 跳过，CI 真跑） | `tests/test_migrations.py`：清表 → upgrade head → 断言 `duration_ms` → downgrade base → 断言表已删 → upgrade head；CI service 提供 DSN 时 0 skip；**该测试当场暴露并修掉两个真实缺陷**：0001 downgrade 先 DROP INDEX 触发 MySQL 1553（已改为先删子表）、老库 create_all 不补 duration_ms（已加等价 ALTER 兜底） | — | — | CI 首次带该用例的全绿为最终证据 |
| G-16 | DDL 单一来源 | 启动时 `create_all` 与 Alembic 双轨 | `src/agentkernel/memory/factory.py:36`；`memory/mysql_store.py:78-118`；`rag/mysql_store.py:58-122` | 高：schema 漂移、迁移回滚后又被自动建回 | **P0** | 删除 `create_all`，仅 `--migrate`/Alembic 建表 |
| G-17 | 备份策略（RPO ≤24h） | ✅ **已实现** | `scripts/backup.py` + `make backup`：`mysqldump --single-transaction`、口令走 `MYSQL_PWD`、保留 7 份 + sha256；产物在 `backups/`（已 gitignore） | 低：依赖 mysqldump/docker 客户端 | — | 首次备份已生成（2.2KB）；演练中暴露并修掉「`--databases` 会把 USE 带回源库」的坑 |
| G-18 | 恢复演练（≤30 天） | ✅ **已完成 1 次** | `scripts/restore_drill.py` + `make restore-drill`：恢复到临时库、比对 5 张表行数、计时；报告 [reports/restore-drill-20261029.md](./reports/restore-drill-20261029.md)（PASS，0.9s，行数全对） | 低：临时库需要管理员权限（root） | — | 下次演练 ≤30 天内；CI 未接（属运维动作） |
| G-19 | 版本化发布与回滚单元 | 版本恒为 `0.1.0`，无 tag/wheel | `pyproject.toml:7`；`git tag` 无输出 | 中：回滚无锚点 | P1 | `v0.2.0` tag + `uv build` 产物 + 回滚步骤验证 |

---

## 4. 可控制（Controllable）

| # | 标准要求（§4.4） | 现状 | 证据 | 风险 | 优先级 | 验收标准 |
|---|---|---|---|---|---|---|
| G-20 | 工具白名单 | ✅ 已达标 | `tools/contracts.py:67-73`；`runtime/agent.py:202-207`；`registry.py:104-110` | — | — | 保持；新增工具需 ADR |
| G-21 | 禁止 shell/eval | ✅ 已达标 | `tools/builtin.py:17-53` AST 白名单；grep 无 `eval(`/`exec(`/`shell=True` | — | — | 保持 |
| G-22 | 外部 MCP 命令 allowlist + env 清洗 | ✅ **已实现**：`--mcp-profile` 命名 profile + 精确 argv；解释器需 `allow_interpreter`；env 白名单剔除密钥；`--mcp` 需 `AGENTKERNEL_ALLOW_RAW_MCP=1` | `mcp/profiles.py`、`mcp/client.py`（`env=` 传入 Popen）、`__main__.py`；`mcp_profiles.example.toml` | 低：raw 逃生口仍存在（显式开启+警告），属运维决策 | — | 负向测试：未知 profile、相对命令、解释器未声明、`-c` 参数、env 泄漏 |
| G-23 | 文档读取根目录白名单 + 大小/数量/深度限制 | ✅ **已实现**：CLI `/ingest`、`--docs` 与 MCP server 位置参数统一走 `utils/paths.py`；默认根 = cwd，可配 `AGENTKERNEL_DOC_ROOTS` | `utils/paths.py`、`__main__.py`、`mcp/server.py`、`.env.example` | 低：`/history` 文案未变；改根目录需要重启 | — | 负向测试 6 条：`../`、symlink 文件逃逸、symlink 目录不遍历、超大小、超数量、根外绝对路径 |
| G-24 | 出站端点 allowlist | ✅ **已实现** | `utils/env.py`：`validate_base_url()`（https 强制、主机白名单、拒绝 userinfo、本机回环例外）；CLI 启动与 `llm._get_client()` 双重校验；8 个测试 | — | — | allowlist 可用 `AGENTKERNEL_ALLOWED_LLM_HOSTS` 覆盖 |
| G-25 | 会话级预算（token/调用数） | 只有 `MAX_STEPS=10` 与 256KB payload | `agent.py:59`；`json_repair.py:22`；`env.py:40-47` | 中：长会话/多工具可放大成本 | P1 | 超预算降级并记录 `budget_exceeded` |
| G-26 | 参数长度/格式校验 | 手写 schema 子集，无 maxLength/pattern | `registry.py:47-97`；内置工具未设 `additionalProperties:false`（`builtin.py:76-85`） | 中：超长字符串直通 | P2 | 增加 maxLength/pattern；多余参数拒绝 |
| G-27 | 工具结果作为不可信数据隔离 | 原样 `role=user` 入历史 | `runtime/agent.py:107-109`；知识库正文进 system prompt（`agent.py:114`） | 中：间接提示注入放大 | P1 | 结果加边界标记 + 注入用例 |

---

## 5. 可验证（Verifiable）

| # | 标准要求（§4.5） | 现状 | 证据 | 风险 | 优先级 | 验收标准 |
|---|---|---|---|---|---|---|
| G-28 | 测试全绿 | ✅ 本地 108 passed/5 skipped；**CI 113 passed / 0 skipped**（114 个测试函数） | 本地 `.venv/bin/python -m pytest -q`；CI：https://github.com/ikun-ikun1/AgentKernel/actions/workflows/ci.yml | — | — | 保持；CI 强制 0 skip（`grep -q SKIPPED`） |
| G-29 | MySQL 集成测试必须真跑 | ✅ CI 已真跑（MySQL 8.0.46 service + DSN，0 skip） | `.github/workflows/ci.yml` test job；PR #1 全绿合并 `20f2b0c`（用户确认；CI：https://github.com/ikun-ikun1/AgentKernel/actions/workflows/ci.yml） | — | — | 保持；PDF 用例由 `pdf` extra 真跑，`grep -q SKIPPED` 强制 0 skip |
| G-30 | 覆盖率门槛 ≥80%，核心 ≥90% | 无覆盖率工具、无阈值；**P0-1 未包含 pytest-cov，明确延后批二**（不要当成已装） | `pytest --cov` → `unrecognized arguments`；`pyproject.toml` 无 `[tool.coverage]`；`uv.lock` 中无 pytest-cov；3 个模块从未被 import（`__main__.py`、`memory/mysql_store.py`、`rag/mysql_store.py`） | 高：改坏关键路径无人知 | **P0（批二）** | 补 `pytest-cov` + 覆盖率报告 + `fail_under=80` 进 `make check`；在批二开工前不得声称「覆盖率已达标」 |
| G-44 | 干净环境安装验收（P0-1 遗留） | ✅ **已关闭**：PR #1 CI 首次全绿（`uv sync --frozen --extra dev --extra mysql --extra pdf` 在干净 runner 完成；当时 68 passed / 0 skipped，当前 99/0） | PR #1 → merge commit `20f2b0c`；workflow `.github/workflows/ci.yml`（权限 `contents: read`）；用户确认 2026-10-29（CI：https://github.com/ikun-ikun1/AgentKernel/actions/workflows/ci.yml） | — | — | 已关闭；后续干净环境验收复用 CI，不再用本地 worktree |
| G-31 | 静态检查 0 退出 | ✅ **已实现** | `ruff check` → `All checks passed!`；`ruff format --check` → 全部已格式化；`mypy src` → 28 文件 0 错误；均在 `make check` 内 | — | — | 保持 |
| G-32 | golden set ≥50（mock）/≥20（live） | 5 条 mock + 4 条 live | `eval.py:59-171,174-223` | 高：S1/S2 无统计意义 | **P0** | 50/20 条，进 `make check` 与 CI |
| G-33 | 模糊测试（坏 JSON/非法帧） | 有 13+5 条定点用例，无 fuzz 语料 | `tests/test_json_repair.py`；`tests/test_mcp.py:97-124` | 中：解析层边界靠运气 | P1 | 500+100 条语料，0 崩溃 0 挂起 |
| G-34 | 安全扫描（gitleaks/semgrep/pip-audit） | 均未接入 | `ls .pre-commit-config.yaml`/`.gitleaks.toml`/`semgrep.yml` → 不存在 | 高：密钥与高危依赖靠人眼 | **P0** | 三类扫描 0 high，进 `make check` |
| G-41 | 文档与实测一致 | ✅ **已修复**：README 重写为「114 个测试；本地 108/5、CI 113/0」双口径；里程碑/面试材料加历史标注 | `README.md`、`docs/status.md`、`docs/README.md`；一致性由 `status.md` 单点维护 | — | — | 后续数字只改 `status.md`，其他文档引用它 |

---

## 6. 可运维（Operable）

| # | 标准要求（§4.6） | 现状 | 证据 | 风险 | 优先级 | 验收标准 |
|---|---|---|---|---|---|---|
| G-35 | Runbook（6 场景） | 无 | 无 `docs/runbook.md` | 中：凌晨出事无步骤（个人项目=自己明天出事） | **P0** | 6 场景各含现象/排查/修复/回滚 |
| G-36 | `make doctor` 体检 | 无 | 无 Makefile；启动失败才报错（`__main__.py:274-290`） | 中：排障靠读栈 | P1 | 一条命令输出 7 项体检结果 |
| G-37 | SLO 周报 | 无 | 无 `docs/reports/` | 中：SLO 只存在于文档 | P1 | `make report` 生成周报并入库 |
| G-38 | 事故模板/复盘 | 无 | 仓库无 incident 模板 | 低 | P2 | 模板 + 首次复盘记录 |
| G-39 | CHANGELOG + semver tag | 无 | `git tag` 空；无 CHANGELOG | 中：变更不可追溯 | P1 | 首个 tag 与 CHANGELOG |
| G-40 | 依赖降级路径 | ✅ 模型失败不崩、向量缺失回退 ngram | `__main__.py:205-209`；`rag/ingest.py:484-499` | — | — | 保持 |

---

## 7. 已满足项（不是欠账，避免只列缺点）

| 能力 | 证据 | 备注 |
|---|---|---|
| 工具白名单 + 未注册不执行 | `tools/contracts.py:67-73`、`runtime/agent.py:202-207` | 单测覆盖（`tests/test_agent.py:95`） |
| 无 shell / 无 eval，计算器 AST 白名单 + 指数/位宽上限 | `tools/builtin.py:17-53` | 单测覆盖（`tests/test_registry.py:59`） |
| SQL 全参数绑定 | `memory/mysql_store.py:177-192`；`rag/mysql_store.py:212-219` | grep 无 f-string SQL |
| MCP 帧长度/头长度/超时/半帧保护 | `mcp/framing.py:26-27,46-63,99-104` | 部分分支无用例（见 G-33） |
| `.env` 不入库且权限 600 | `.gitignore:7`；`ls -l .env` → `-rw-------`；`git ls-files .env` 不匹配 | 密钥卫生基本合规 |
| API key 只在环境变量、异常不含值 | `utils/env.py:21-29`；`llm.py:64-65` | DSN 异常路径仍需脱敏（G-13 关联） |
| 死锁：进程内按会话串行 + 3 次有界重试 | `memory/mysql_store.py:26-30,50-60,174-201`（提交 1597ec4） | 跨进程无效（G-29 关联） |
| 文档入库 checksum 幂等 | `rag/ingest.py:517-520,560-562`；单测 `tests/test_rag.py:76-93` | S6③ 已有实现 |
| 迁移 0001 对称 downgrade | `migrations/versions/0001_initial.py:78-88` | 仅缺测试（G-15） |
| mock eval 有阈值、非零退出 | `eval.py:246-248` | 仅缺规模与 CI（G-32） |
| mypy 全绿 | `mypy src` → 25 文件 0 错误 | 保持 |

---

## 8. 路线图（P0 / P1 / P2）

### 8.1 P0（批一已执行；1/2/4/5 已完成，3 已改为 Dockerfile，覆盖率与 golden set 移入批二）

> 批一范围 = 下表 5 项。覆盖率门槛 + golden set 50 条排在**批二**；`pytest-cov` 随批二补，批一不装。

| 序 | 任务 | 覆盖差距 | 预估 | 依赖 |
|---|---|---|---|---|
| 1 | 建 `Makefile` + GitHub Actions；修 ruff I001；含一个**纯格式化提交**（32 文件）后再启用 `format --check` | G-05, G-28, G-31, G-43 | 0.75 天 | D2 允许 CI（已确认） |
| 2 | `uv lock` + `.python-version` + MySQL digest + 删默认口令 | G-01, G-02, G-04, G-06 | 0.5 天 | — |
| 3 | 覆盖率工具 + 阈值 + golden set 5→50 + eval 入 `make check` | G-30, G-32, G-29（CI service） | 1.5 天 | 1 |
| 4 | 结构化日志 + trace_id + token/成本 + 脱敏 | G-07…G-13 | 1.5 天 | 1 |
| 5 | MCP env 白名单 + 文档根白名单 + DSN 异常脱敏 + 3306 绑本地 | G-22, G-23, G-13 | 1 天 | — |

合计约 5 人日；完成后再跑一遍本文件的表格，P0 项全部应转 PASS。

### 8.2 P1（1–2 个迭代）

G-15/G-16（迁移测试 + 去双轨 DDL）、G-17/G-18（备份与首次恢复演练）、G-19（tag+CHANGELOG）、G-10/G-11（指标与耗时落库）、G-24（base_url allowlist）、G-25（会话预算）、G-27（不可信数据隔离）、G-33（fuzz 语料）、G-35/G-36/G-37（runbook + doctor + 周报）。

### 8.3 P2

G-26（schema 长度/格式）、G-38（事故模板）、OTLP 导出、mypy `--strict`、向量索引重建入口（ADR-001 自陈缺口）、多版本矩阵。

---

## 9. 复现命令

```bash
cd /home/ikun/AgentKernel

# 测试与静态检查
.venv/bin/python -m pytest -q              # 108 passed, 5 skipped（有 DSN 时 113 passed）
.venv/bin/python -m ruff check .           # All checks passed!（EXIT=0）
.venv/bin/python -m mypy src               # Success: no issues found in 25 source files
.venv/bin/python -m pytest --cov=agentkernel --cov-report=term-missing -q   # 不支持 --cov（pytest-cov 未装）
.venv/bin/python -c "import coverage"      # ModuleNotFoundError

# 评测
.venv/bin/python eval.py                   # 通过 5/5，EXIT=0

# 资产盘点
ls .github Makefile uv.lock .pre-commit-config.yaml .gitleaks.toml 2>&1   # 均 No such file
git tag                                     # 空
git ls-files | wc -l                        # 59

# 环境
.venv/bin/python -V ; python3 -V            # 3.11.15 / 3.14.4
.venv/bin/python -m pip --version           # No module named pip
docker ps --format '{{.Names}} {{.Image}} {{.Status}}'   # agentkernel-mysql ... mysql:8.0 Up (healthy)
```

> 复现环境：2026-10-29，HEAD=`73537e9`，`git status --porcelain` 为空（除本文件与 `docs/production-standard.md` 为新增文档）。
