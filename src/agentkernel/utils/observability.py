"""结构化运行日志（P0-4）。

职责边界：
- 只做「记录」：JSONL 一行一条事件，供 `make report` 聚合；不参与业务判断。
- 字段表：12 核心（恒有）+ 条件字段（tool_name/cost_usd/span/pricing_table_version；审批工具另带 approval_decision/reviewer/idempotency_key/argument_summary/approval_timestamp；幂等命中带 deduplicated）。
- 成本：定价表带版本号；未知模型返回 `None` 并告警一次，禁止静默算 0。
- 脱敏：`sk-`、`password=`、DSN 里的口令、Bearer token 一律替换为 `***`。
- 未配置 handler 时退回 stderr；`AGENTKERNEL_LOG` 指向文件时写 JSONL 文件。
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import sys
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

LOGGER_NAME = "agentkernel.runtime"

# 定价表版本与快照日期（USD / 1M tokens）。改价必须同时改版本号并更新 docs/pricing.md。
PRICING_TABLE_VERSION = "2026-10-29"
PRICING_USD_PER_1M: dict[str, tuple[float, float]] = {
    "deepseek-chat": (0.27, 1.10),
    "deepseek-reasoner": (0.55, 2.19),
}

MAX_FIELD_CHARS = 4096

CORE_FIELDS = (
    "ts",
    "level",
    "event",
    "trace_id",
    "session_id_hash",
    "turn_id",
    "step",
    "latency_ms",
    "model",
    "tokens",
    "success",
    "error_type",
)
CONDITIONAL_FIELDS = (
    "tool_name",
    "cost_usd",
    "span",
    "pricing_table_version",
    "decision",
    "approval_decision",
    "reviewer",
    "idempotency_key",
    "argument_summary",
    "approval_timestamp",
    "deduplicated",
)

_REDACTIONS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"sk-[A-Za-z0-9_\-]{6,}"), "sk-***"),
    (
        re.compile(r"(?i)(api[_-]?key|token|password|secret)(\s*[=:]\s*)[^\s,;\"']+"),
        r"\1\2***",
    ),
    (re.compile(r"://([^:/@\s]+):([^@/\s]+)@"), r"://\1:***@"),
    (re.compile(r"(?i)bearer\s+[A-Za-z0-9._\-]+"), "Bearer ***"),
)


@dataclass(frozen=True)
class Usage:
    prompt_tokens: int
    completion_tokens: int


def redact(text: str) -> str:
    """抹掉常见凭据形态；幂等，可对同一串重复调用。"""
    for pattern, repl in _REDACTIONS:
        text = pattern.sub(repl, text)
    return text


def truncate(text: str, limit: int = MAX_FIELD_CHARS) -> str:
    if len(text) <= limit:
        return text
    return f"{text[:limit]}…<truncated {len(text) - limit} chars>"


def hash_session(session_id: str | None) -> str | None:
    """会话 ID 不进日志；只留 12 位 sha256，便于关联但不泄露。"""
    if not session_id:
        return None
    return hashlib.sha256(session_id.encode("utf-8")).hexdigest()[:12]


def new_trace_id() -> str:
    return uuid.uuid4().hex


def new_turn_id() -> str:
    return uuid.uuid4().hex[:8]


def new_span_id() -> str:
    """W3C 兼容的 64-bit span id（16 hex）；trace_id 是 32 hex（128-bit）。"""
    return uuid.uuid4().hex[:16]


_warned_models: set[str] = set()


def reset_pricing_warnings() -> None:
    """仅测试使用：让未知模型告警可以重新触发。"""
    _warned_models.clear()


def cost_usd(model: str | None, usage: Usage | None) -> float | None:
    """按版本化定价表算成本；未知模型返回 None（不是 0）。"""
    if usage is None or not model:
        return None
    price = PRICING_USD_PER_1M.get(model)
    if price is None:
        if model not in _warned_models:
            _warned_models.add(model)
            logging.getLogger(LOGGER_NAME).warning(
                json.dumps(
                    {
                        "event": "pricing_unknown",
                        "model": model,
                        "pricing_table_version": PRICING_TABLE_VERSION,
                        "level": "WARNING",
                    },
                    ensure_ascii=False,
                )
            )
        return None
    prompt_price, completion_price = price
    return round(
        (usage.prompt_tokens / 1_000_000) * prompt_price
        + (usage.completion_tokens / 1_000_000) * completion_price,
        6,
    )


class JsonlFormatter(logging.Formatter):
    """把 `record.ak` 里的字段合并成一行 JSON。"""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = dict(getattr(record, "ak", {}) or {})
        line: dict[str, Any] = {
            "ts": datetime.now(UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "event": payload.pop("event", "log"),
        }
        for key, value in payload.items():
            if isinstance(value, str):
                value = truncate(redact(value))
            line[key] = value
        return json.dumps(line, ensure_ascii=False, default=str)


_configured = False


def configure(*, path: str | None = None, level: int = logging.INFO) -> None:
    """幂等配置。path=None 时读 `AGENTKERNEL_LOG`，都没有就写 stderr。"""
    global _configured
    if _configured:
        return
    logger = logging.getLogger(LOGGER_NAME)
    logger.disabled = False  # alembic fileConfig 等可能把 logger 禁用掉
    logger.setLevel(level)
    logger.propagate = False
    target = path or os.environ.get("AGENTKERNEL_LOG")
    if target:
        os.makedirs(os.path.dirname(os.path.abspath(target)) or ".", exist_ok=True)
        handler: logging.Handler = logging.FileHandler(target, encoding="utf-8")
    else:
        handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(JsonlFormatter())
    logger.addHandler(handler)
    _configured = True


def reset_for_tests() -> None:
    """仅测试使用：清空 handler，避免跨用例重复输出。"""
    global _configured
    logger = logging.getLogger(LOGGER_NAME)
    logger.disabled = False
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()
    # 恢复传播，避免影响 caplog 等依赖 root handler 的测试
    logger.propagate = True
    _configured = False


def emit(event: str, *, level: int = logging.INFO, **fields: Any) -> None:
    """发一条结构化事件；记录失败不得影响主流程。"""
    try:
        logging.getLogger(LOGGER_NAME).log(level, event, extra={"ak": {"event": event, **fields}})
        # G-47：配置了 OTEL_EXPORTER_OTLP_ENDPOINT 时异步镜像到 OTLP/HTTP
        from agentkernel.utils import otel

        otel.record(event, **fields)
    except Exception:  # 观测失败不能拖垮主流程
        pass
