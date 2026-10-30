"""MCP 帧协议边界（补齐 framing.py 未覆盖分支）。"""

from __future__ import annotations

import io

import pytest

from agentkernel.mcp.framing import (
    MCPFramingError,
    frame_message,
    read_frame,
    write_message,
)


def test_rejects_non_positive_max_frame() -> None:
    with pytest.raises(ValueError, match="必须大于 0"):
        read_frame(io.BytesIO(b""), max_frame_bytes=0)


def test_rejects_oversized_header() -> None:
    header = b"X-Pad: " + b"a" * 9000 + b"\r\n\r\n"
    with pytest.raises(MCPFramingError, match="header 超过大小限制"):
        read_frame(io.BytesIO(header))


def test_rejects_header_without_colon() -> None:
    with pytest.raises(MCPFramingError, match="非法 MCP header"):
        read_frame(io.BytesIO(b"BadHeader\r\n\r\n"))


def test_rejects_non_integer_content_length() -> None:
    with pytest.raises(MCPFramingError, match="非法 Content-Length"):
        read_frame(io.BytesIO(b"Content-Length: abc\r\n\r\n"))


def test_rejects_negative_content_length() -> None:
    with pytest.raises(MCPFramingError, match="Content-Length 超出限制"):
        read_frame(io.BytesIO(b"Content-Length: -1\r\n\r\n"))


def test_rejects_body_closed_mid_frame() -> None:
    with pytest.raises(MCPFramingError, match="消息体中途关闭"):
        read_frame(io.BytesIO(b"Content-Length: 10\r\n\r\nabc"))


def test_timeout_requires_selectable_stream() -> None:
    with pytest.raises(MCPFramingError):
        read_frame(io.StringIO(""), timeout=0.1)


def test_write_then_read_roundtrip() -> None:
    buffer = io.BytesIO()
    write_message(buffer, {"jsonrpc": "2.0", "id": 1, "result": {"ok": True}})
    body = read_frame(io.BytesIO(buffer.getvalue()))
    assert b'"ok": true' in body


def test_frame_message_length_prefix() -> None:
    framed = frame_message(b"{}")
    assert framed.startswith(b"Content-Length: 2\r\n\r\n")
