"""可选 OTLP/HTTP JSON 导出（G-47）。

设计取舍：
- 只依赖标准库：OTLP/HTTP 的 JSON 编码足够表达 trace/span，避免为单机 CLI 引入
  opentelemetry-sdk + protobuf 的重量级依赖；接在线 collector 时无需改业务代码。
- 默认关闭：只有设置 `OTEL_EXPORTER_OTLP_ENDPOINT` 才启动后台线程。
- 有界队列 + 丢弃最旧：collector 变慢/不可达时不能拖垮主流程，也不能无限占内存。
- 无递归：导出失败只计数，不调用 observability.emit。

环境变量：
- `OTEL_EXPORTER_OTLP_ENDPOINT`：collector 根地址（自动补 `/v1/traces`）或完整 URL。
"""

from __future__ import annotations

import atexit
import json
import os
import queue
import re
import threading
import time
import urllib.request
import uuid
from typing import Any

from agentkernel import __version__

SERVICE_NAME = "agentkernel"
MAX_QUEUE = 256
HTTP_TIMEOUT_SECONDS = 2.0
_HEX32 = re.compile(r"^[0-9a-f]{32}$")
_HEX16 = re.compile(r"^[0-9a-f]{16}$")


def endpoint() -> str | None:
    """返回完整 traces URL；未配置返回 None。"""
    raw = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", "").strip()
    if not raw:
        return None
    if raw.endswith("/v1/traces"):
        return raw
    return raw.rstrip("/") + "/v1/traces"


def _redact(text: str) -> str:
    # 延迟导入避免 observability <-> otel 的循环导入
    from agentkernel.utils.observability import redact, truncate

    return truncate(redact(text))


def _attribute_value(value: Any) -> dict[str, Any] | None:
    if isinstance(value, bool):
        return {"boolValue": value}
    if isinstance(value, int):
        return {"intValue": str(value)}
    if isinstance(value, float):
        return {"doubleValue": value}
    if isinstance(value, str):
        return {"stringValue": _redact(value)}
    return None


def _attributes(fields: dict[str, Any]) -> list[dict[str, Any]]:
    attrs: list[dict[str, Any]] = []
    for key, value in fields.items():
        if key in {"trace_id", "span"}:
            continue
        encoded = _attribute_value(value)
        if encoded is not None:
            attrs.append({"key": key, "value": encoded})
    span = fields.get("span")
    if isinstance(span, dict):
        for key in ("id", "parent_id", "name"):
            if isinstance(span.get(key), str):
                attrs.append({"key": f"span.{key}", "value": {"stringValue": span[key]}})
    return attrs


def build_payload(event: str, fields: dict[str, Any]) -> dict[str, Any]:
    """把一条 JSONL 事件转换成 OTLP/HTTP JSON（resourceSpans）。"""
    now_ns = time.time_ns()
    latency_ms = fields.get("latency_ms")
    latency_ns = int(float(latency_ms) * 1_000_000) if isinstance(latency_ms, (int, float)) else 0
    trace_id = fields.get("trace_id")
    if not (isinstance(trace_id, str) and _HEX32.match(trace_id)):
        trace_id = uuid.uuid4().hex
    span = fields.get("span")
    span_id = span.get("id") if isinstance(span, dict) else None
    if not (isinstance(span_id, str) and _HEX16.match(span_id)):
        span_id = uuid.uuid4().hex[:16]
    success = fields.get("success")
    span_payload: dict[str, Any] = {
        "traceId": trace_id,
        "spanId": span_id,
        "name": event,
        "kind": 1,
        "startTimeUnixNano": str(max(0, now_ns - latency_ns)),
        "endTimeUnixNano": str(now_ns),
        "attributes": _attributes(fields),
    }
    parent = span.get("parent_id") if isinstance(span, dict) else None
    if isinstance(parent, str) and _HEX16.match(parent):
        span_payload["parentSpanId"] = parent
    if success is False:
        span_payload["status"] = {"code": 2, "message": str(fields.get("error_type") or "error")}
    return {
        "resourceSpans": [
            {
                "resource": {
                    "attributes": [
                        {"key": "service.name", "value": {"stringValue": SERVICE_NAME}},
                        {
                            "key": "service.version",
                            "value": {
                                "stringValue": os.environ.get("AGENTKERNEL_VERSION", __version__)
                            },
                        },
                    ]
                },
                "scopeSpans": [
                    {
                        "scope": {"name": "agentkernel.observability"},
                        "spans": [span_payload],
                    }
                ],
            }
        ]
    }


class _Exporter:
    def __init__(self, url: str) -> None:
        self.url = url
        self._queue: queue.Queue[dict[str, Any] | None] = queue.Queue(maxsize=MAX_QUEUE)
        self._thread = threading.Thread(target=self._run, name="agentkernel-otel", daemon=True)
        self._thread.start()
        self.dropped = 0

    def submit(self, payload: dict[str, Any]) -> None:
        try:
            self._queue.put_nowait(payload)
        except queue.Full:
            self.dropped += 1
            try:
                self._queue.get_nowait()  # 丢最旧，保最新
                self._queue.put_nowait(payload)
            except (queue.Empty, queue.Full):
                pass

    def _run(self) -> None:
        while True:
            payload = self._queue.get()
            if payload is None:
                return
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            request = urllib.request.Request(
                self.url,
                data=body,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            try:
                with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT_SECONDS):
                    pass
            except Exception:  # 导出失败不能影响主流程；也不递归写事件
                pass

    def shutdown(self, timeout: float = 3.0) -> None:
        self._queue.put(None)
        self._thread.join(timeout=timeout)


_exporter: _Exporter | None = None
_lock = threading.Lock()


def record(event: str, **fields: Any) -> None:
    """异步导出一条事件；未配置 endpoint 时是廉价的 no-op。"""
    global _exporter
    url = endpoint()
    if url is None:
        return
    with _lock:
        if _exporter is None or _exporter.url != url:
            if _exporter is not None:
                _exporter.shutdown()
            _exporter = _Exporter(url)
        exporter = _exporter
    exporter.submit(build_payload(event, fields))


def shutdown() -> None:
    """测试/退出前 flush（有界等待，不保证 collector 一定收到）。"""
    global _exporter
    with _lock:
        exporter, _exporter = _exporter, None
    if exporter is not None:
        exporter.shutdown()


def reset_for_tests() -> None:
    shutdown()


atexit.register(shutdown)
