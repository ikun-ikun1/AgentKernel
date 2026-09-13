"""MCP stdio 传输帧协议（教学点：agent-study Ch10.6 stdio 传输）。

MCP 官方 stdio 传输使用 LSP 风格的帧格式：
    Content-Length: <字节数>\r\n
    \r\n
    <JSON-RPC 消息体>

规则：
- 协议消息走 stdout；所有日志/调试输出必须走 stderr（否则 Client 解析失败）。
- 每个帧一个完整 JSON-RPC 消息。
"""
from __future__ import annotations

import json
import select
import time
from typing import Any

from agentkernel.utils.errors import AgentKernelError


class MCPFramingError(AgentKernelError):
    """MCP 帧协议错误。"""


DEFAULT_MAX_FRAME_BYTES = 4 * 1024 * 1024
MAX_HEADER_BYTES = 8 * 1024


def frame_message(message: bytes) -> bytes:
    """把一个消息体编码为带 Content-Length 头的帧。"""
    return b"Content-Length: " + str(len(message)).encode() + b"\r\n\r\n" + message


def _readline(stream: Any, timeout: float | None) -> bytes:
    if timeout is not None:
        try:
            ready, _, _ = select.select([stream], [], [], timeout)
        except (OSError, TypeError) as e:
            raise MCPFramingError("MCP 流不支持超时读取") from e
        if not ready:
            raise MCPFramingError("MCP 读取帧超时")
    return stream.readline()


def _read_body(stream: Any, size: int, deadline: float | None) -> bytes:
    chunks: list[bytes] = []
    remaining = size
    while remaining > 0:
        if deadline is not None:
            timeout = max(0.0, deadline - time.monotonic())
            try:
                ready, _, _ = select.select([stream], [], [], timeout)
            except (OSError, TypeError) as e:
                raise MCPFramingError("MCP 流不支持超时读取") from e
            if not ready:
                raise MCPFramingError("MCP 读取消息体超时")
        chunk = stream.read(remaining)
        if not chunk:
            raise MCPFramingError("MCP 连接在消息体中途关闭")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def read_frame(
    stream: Any,
    *,
    max_frame_bytes: int = DEFAULT_MAX_FRAME_BYTES,
    timeout: float | None = None,
) -> bytes:
    """从二进制流读取一个 Content-Length 帧，返回消息体字节串。"""
    if max_frame_bytes <= 0:
        raise ValueError("max_frame_bytes 必须大于 0")
    deadline = None if timeout is None else time.monotonic() + timeout
    headers: dict[str, str] = {}
    header_bytes = 0
    while True:
        remaining_timeout = (
            None if deadline is None else max(0.0, deadline - time.monotonic())
        )
        line = _readline(stream, remaining_timeout)
        if not line:
            raise MCPFramingError("MCP 连接已关闭")
        header_bytes += len(line)
        if header_bytes > MAX_HEADER_BYTES:
            raise MCPFramingError("MCP header 超过大小限制")
        if line in (b"\r\n", b"\n"):
            break
        text = line.decode("utf-8", errors="replace").strip()
        if ":" not in text:
            raise MCPFramingError("非法 MCP header")
        key, _, value = text.partition(":")
        headers[key.strip().lower()] = value.strip()

    raw_length = headers.get("content-length")
    if raw_length is None:
        raise MCPFramingError("缺少 Content-Length")
    try:
        length = int(raw_length)
    except ValueError as e:
        raise MCPFramingError(f"非法 Content-Length：{raw_length!r}") from e
    if length < 0 or length > max_frame_bytes:
        raise MCPFramingError(f"Content-Length 超出限制：{length}")
    return _read_body(stream, length, deadline)


def write_message(stream: Any, message: dict[str, Any]) -> None:
    """把 JSON-RPC 消息编码为 JSON 并写入流（含 flush）。"""
    body = json.dumps(message, ensure_ascii=False).encode("utf-8")
    stream.write(frame_message(body))
    stream.flush()
