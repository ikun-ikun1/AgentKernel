# AgentKernel 工具链入口。
#
# 约定（见 docs/production-standard.md §4.1）：
# - `make check` 不修改 .venv，使用当前解释器；CI 先 `make sync` 再 `make check`，二者命令同源。
# - 依赖安装一律走 lock：`make sync` = `uv sync --frozen --extra dev --extra mysql`。
#   dev/mysql/rag/mcp 都是 [project.optional-dependencies]，因此用 --extra 而不是 --group。
# - 格式门禁自 chore/format-baseline 起接入 `check`；格式化提交已写入 .git-blame-ignore-revs。
# - PDF 用例依赖 PyMuPDF：用轻量 pdf extra（只装 pymupdf，不引入 chromadb/torch），CI 因此可以 0 skip。
# - CI 在 make check 之后用 `grep -q SKIPPED check.log` 强制 0 skip（pytest 有 skip 仍返回 0）。

SHELL := /bin/bash

PY ?= $(shell if [ -x .venv/bin/python ]; then echo .venv/bin/python; else echo python3; fi)
UV ?= uv
EXTRAS ?= --extra dev --extra mysql --extra pdf
PYTEST_ARGS ?=
DOCKER_IMAGE ?= agentkernel:local
# 本地 docker.io 不可达时可覆盖，例如 make docker-build DOCKER_BASE=docker.m.daocloud.io/library/python:3.11-slim
DOCKER_BASE ?= python:3.11.15-slim

.PHONY: help require-env sync sync-all format format-check lint type test eval report check docker-build docker-smoke docker-nonroot docker-size

help:
	@echo "make sync         安装锁定依赖（uv sync --frozen $(EXTRAS)）"
	@echo "make test PYTEST_ARGS='-k pdf'  透传 pytest 参数"
	@echo "make sync-all     安装全部 extras（含 rag/mcp，体积大）"
	@echo "make format       格式化（ruff format）"
	@echo "make format-check 校验格式（check 已包含）"
	@echo "make lint         ruff check"
	@echo "make type         mypy src"
	@echo "make test         pytest -q -rs $(PYTEST_ARGS)"
	@echo "make eval         eval.py（mock，无需 API Key）"
	@echo "make report       从 JSONL 日志生成 SLO 周报（AGENTKERNEL_LOG 指向日志文件）"
	@echo "make check        lint + format-check + type + test + eval"
	@echo "make docker-smoke 构建镜像并跑启动 smoke（--db :memory:，只证明能启动）"

require-env:
	@command -v $(PY) >/dev/null 2>&1 || { echo "缺少 Python 解释器：$(PY)；先执行 make sync 或激活 .venv"; exit 1; }

sync:
	$(UV) sync --frozen $(EXTRAS)

sync-all:
	$(UV) sync --frozen --all-extras

format:
	$(PY) -m ruff format .

format-check:
	$(PY) -m ruff format --check .

lint:
	$(PY) -m ruff check .

type:
	$(PY) -m mypy src

test:
	$(PY) -m pytest -q -rs $(PYTEST_ARGS)

eval:
	$(PY) eval.py

report:
	$(PY) scripts/report.py $(if $(AGENTKERNEL_LOG),--log $(AGENTKERNEL_LOG),)

check: require-env lint format-check type test eval
	@echo "make check: OK"

docker-build:
	docker build --build-arg PYTHON_IMAGE=$(DOCKER_BASE) -t $(DOCKER_IMAGE) .

docker-smoke: docker-build
	printf '/quit\n' | docker run -i --rm $(DOCKER_IMAGE) python -m agentkernel --db :memory: --kb-db :memory: --kb-backend lexical | tee /tmp/agentkernel-smoke.log
	grep -q 'AgentKernel 已启动' /tmp/agentkernel-smoke.log

docker-nonroot: docker-build
	@uid=$$(docker run --rm $(DOCKER_IMAGE) id -u); test "$$uid" != "0"; echo "non-root uid=$$uid"

docker-size: docker-build
	@docker images $(DOCKER_IMAGE) --format 'image size (docker images): {{.Size}}'
	@docker image inspect $(DOCKER_IMAGE) --format 'compressed layers: {{.Size}} bytes'
