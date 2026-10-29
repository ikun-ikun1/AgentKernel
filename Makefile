# AgentKernel 工具链入口。
#
# 约定（见 docs/production-standard.md §4.1）：
# - `make check` 不修改 .venv，使用当前解释器；CI 先 `make sync` 再 `make check`，二者命令同源。
# - 依赖安装一律走 lock：`make sync` = `uv sync --frozen --extra dev --extra mysql`。
#   dev/mysql/rag/mcp 都是 [project.optional-dependencies]，因此用 --extra 而不是 --group。
# - `format-check` 目标已就绪，但暂不接入 `check`；等 chore/format-baseline 合并后再加（避免机械 diff 混入本 PR）。
# - 已知环境依赖：tests/test_rag.py:102 用 importorskip("fitz") 需要 PyMuPDF（rag extra），
#   未安装时该用例 skip；P0-2 的 0-skip 策略需先拆 rag job 或装 rag extra（见 gap 文档 G-43 附近）。

SHELL := /bin/bash

PY ?= $(shell if [ -x .venv/bin/python ]; then echo .venv/bin/python; else echo python3; fi)
UV ?= uv
EXTRAS ?= --extra dev --extra mysql

.PHONY: help require-env sync sync-all format format-check lint type test eval check

help:
	@echo "make sync         安装锁定依赖（uv sync --frozen $(EXTRAS)）"
	@echo "make sync-all     安装全部 extras（含 rag/mcp，体积大）"
	@echo "make format       格式化（ruff format）"
	@echo "make format-check 校验格式（尚未接入 check）"
	@echo "make lint         ruff check"
	@echo "make type         mypy src"
	@echo "make test         pytest -q -rs"
	@echo "make eval         eval.py（mock，无需 API Key）"
	@echo "make check        lint + type + test + eval"

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
	$(PY) -m pytest -q -rs

eval:
	$(PY) eval.py

check: require-env lint type test eval
	@echo "make check: OK"
