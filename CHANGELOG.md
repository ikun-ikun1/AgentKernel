# Changelog

本项目遵循 [Semantic Versioning](https://semver.org/)；格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)。

## [0.3.0] - 2026-10-30

### Changed

- 架构 A1–A6：CLI 组合根、Memory/LLM/MCP 端口与适配器、RAG 拆分、事件组装外移；旧 import shim 保留一个版本，CLI/schema/安全/D4 行为不变。
- A7.1：`Agent` 接收注入的 `LLMClient`，composition/eval 创建 adapter；`runtime/agent.py` 不再 import `runtime.llm` shim。
- A7.2：ReAct 循环、上下文策略、工具执行/观察格式化外移到 `application/` + `domain/`；`Agent` 变为 184 行 facade。
- A7.3：明确不新增空 EventSink/KnowledgeStore 接口；架构断言覆盖 ports/adapters/observability。

### Tests

- 192 个测试；CI `191 passed / 1 deselected(live) / 0 skipped`；覆盖率 84.4%（门槛 80%）。

## [0.2.0] - 2026-10-30

### Added

- 可选 OTLP/HTTP JSON 导出：`OTEL_EXPORTER_OTLP_ENDPOINT` 开关、后台有界队列、本地假 collector 测试；无外部 SDK 依赖。
- fuzz 语料：固定种子生成 500 条坏 JSON + 100 条非法 MCP 帧，纳入 `make check` 与 `make fuzz`。

### Fixed

- 深层嵌套 JSON 触发 `RecursionError` 时不再向上抛，按不可修复降级为纯文本。

### Tests

- 181 个测试；CI `180 passed / 1 deselected(live) / 0 skipped`；覆盖率 83.34%（门槛 80%）。
- `uv build` 产出 wheel/sdist；在干净 venv 安装 wheel，`agentkernel.__version__ == 0.2.0`，CLI smoke EXIT=0。

## [0.1.0] - 2026-10-30

首个可回滚版本：ReAct Runtime、MCP、MySQL 主存储与观测/安全/运维门禁的第一轮收口。

### Added

- ReAct 主循环、单/多工具调用、观察回灌、上下文 truncate/compact，以及分层 JSON 修复与纯文本降级。
- 手写 JSON Schema 子集校验、工具名 allowlist、payload 上限；AST 计算器，无 shell/eval。
- MySQL 8 主存储（会话/消息/工具审计）、SQLite 测试适配器；SHA-256 增量入库、MySQL ngram、可选 Chroma + RRF。
- MCP client/server；外部 server 只接受命名 profile + 精确 argv + env 白名单。
- 结构化 JSONL 观测（turn/tool/span）、trace_id、token/成本（版本化定价表）、写库前脱敏；`make report/trace/prune`。
- 安全基线：文档根 realpath 白名单、LLM 出站 allowlist、工具结果不可信隔离、gitleaks/semgrep/pip-audit。
- 数据保护：`make backup`（保留 7 份、sha256）、`make restore-drill`（临时库恢复 + 行数校验 + 报告）。
- 会话预算：单会话 150k tokens、单轮 5 次工具调用，超限写 `budget_exceeded` 并降级返回。
- 运维：`docs/runbook.md`（6 场景）、`make doctor`（7 项体检）、事故模板与首次复盘记录。
- CI 4 个 job：test（MySQL service + 0-skip）、eval-minimal、security、docker（<400MB 门禁）。

### Changed

- schema 只由 Alembic 管理（0001/0002），删除启动时 `create_all` 与 ALTER 兜底；缺失时给出 `--migrate` 指引。
- MySQL 端口绑定回环地址；默认口令/默认 DSN 全部移除，缺失即报错。
- 基础镜像改为精确 tag `python:3.11.15-slim` / `mysql:8.0.46`（digest 固定见 G-45/G-46，未完成）。

### Fixed

- 迁移 0001 downgrade 的外键顺序（先删子表，避免 MySQL 1553）；alembic 日志配置不再禁用既有 logger。
- 备份不再把 `CREATE DATABASE/USE` 写回源库；恢复演练先校验目标库名与行数。
- 测试统一使用 `sys.executable`，不再依赖 PATH 中的 `python3.11`。
- MCP 帧解析、JSON 修复边界、CLI 退出码与 schema 校验的缺口用例补齐。

### Security

- 移除内置默认口令（G-06）；DSN/密钥在异常与日志中脱敏。
- 文档读取限制在 `AGENTKERNEL_DOC_ROOTS`，拒绝 `../`、symlink 逃逸、超大小/数量。
- 工具结果以 `<untrusted_tool_result>` 包裹并截断，防止提示注入逃逸。

### Tests

- 174 个测试；CI `173 passed / 1 deselected(live) / 0 skipped`；覆盖率 82.89%（门槛 80%）。
- `make eval`：mock golden set 50/50；live set 20 条数据就绪。

[0.3.0]: https://github.com/ikun-ikun1/AgentKernel/releases/tag/v0.3.0
[0.2.0]: https://github.com/ikun-ikun1/AgentKernel/releases/tag/v0.2.0
[0.1.0]: https://github.com/ikun-ikun1/AgentKernel/releases/tag/v0.1.0
