"""G-47：OTLP/HTTP JSON 导出（本地假 collector，无外部依赖）。"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import ClassVar

from agentkernel.utils import observability, otel


class _Collector(BaseHTTPRequestHandler):
    received: ClassVar[list[dict]] = []
    paths: ClassVar[list[str]] = []

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length)
        type(self).received.append(json.loads(body))
        type(self).paths.append(self.path)
        self.send_response(200)
        self.end_headers()

    def log_message(self, format: str, *args: object) -> None:
        pass


def _server() -> ThreadingHTTPServer:
    _Collector.received = []
    _Collector.paths = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Collector)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def test_otlp_disabled_without_endpoint(monkeypatch) -> None:
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
    otel.reset_for_tests()
    assert otel.endpoint() is None
    observability.emit("turn", success=True)
    assert otel._exporter is None


def test_endpoint_normalization(monkeypatch) -> None:
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://collector:4318/")
    assert otel.endpoint() == "http://collector:4318/v1/traces"
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://collector:4318/v1/traces")
    assert otel.endpoint() == "http://collector:4318/v1/traces"


def test_build_payload_uses_valid_ids_and_redacts() -> None:
    payload = otel.build_payload(
        "tool",
        {
            "trace_id": "not-a-trace",
            "span": {"id": "short", "parent_id": "bad"},
            "latency_ms": 5,
            "success": False,
            "error_type": "sk-abcdef123456",
        },
    )
    span = payload["resourceSpans"][0]["scopeSpans"][0]["spans"][0]
    assert len(span["traceId"]) == 32
    assert len(span["spanId"]) == 16
    assert "parentSpanId" not in span
    assert span["status"]["code"] == 2
    attrs = {a["key"]: a["value"] for a in span["attributes"]}
    assert attrs["error_type"]["stringValue"] == "sk-***"
    assert attrs["span.id"]["stringValue"] == "short"


def test_emit_posts_to_local_collector(monkeypatch, tmp_path: Path) -> None:
    server = _server()
    port = server.server_address[1]
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", f"http://127.0.0.1:{port}")
    otel.reset_for_tests()
    observability.reset_for_tests()
    observability.configure(path=str(tmp_path / "events.jsonl"))
    try:
        observability.emit(
            "turn",
            trace_id="a" * 32,
            span={"id": "b" * 16, "parent_id": None, "name": "turn"},
            latency_ms=12.5,
            success=False,
            error_type="Timeout",
        )
        otel.shutdown()
    finally:
        observability.reset_for_tests()
        otel.reset_for_tests()
        server.shutdown()
        server.server_close()
    assert _Collector.paths == ["/v1/traces"]
    payload = _Collector.received[0]
    span = payload["resourceSpans"][0]["scopeSpans"][0]["spans"][0]
    assert span["traceId"] == "a" * 32
    assert span["spanId"] == "b" * 16
    assert span["name"] == "turn"
    attrs = {a["key"]: a["value"] for a in span["attributes"]}
    assert attrs["latency_ms"]["doubleValue"] == 12.5
