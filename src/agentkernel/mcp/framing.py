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
from typing import Any, BinaryIO

from agentkernel.utils.errors import AgentKernelError


class MCPFramingError(AgentKernelError):
    """MCP 帧协议错误。"""


def frame_message(message: bytes) -> bytes:
    """把一个消息体编码为带 Content-Length 头的帧。"""
    return b"Content-Length: " + str(len(message)).encode() + b"\r\n\r\n" + message


def read_frame(stream: BinaryIO) -> bytes:
    """从二进制流读取一个 Content-Length 帧，返回消息体字节串。"""
    headers: dict[str, str] = {}
    while True:
        line = stream.readline()
        if not line:
            raise MCPFramingError("MCP 连接已关闭")
        if line in (b"\r\n", b"\n"):
            break
        text = line.decode("utf-8", errors="replace").strip()
        if ":" in text:
            key, _, value = text.partition(":")
            headers[key.strip().lower()] = value.strip()

    try:
        length = int(headers.get("content-length", "0"))
    except ValueError as e:
        raise MCPFramingError(f"非法 Content-Length：{headers.get('content-length')!r}") from e

    chunks: list[bytes] = []
    remaining = length
    while remaining > 0:
        chunk = stream.read(remaining)
        if not chunk:
            raise MCPFramingError("MCP 连接在消息体中途关闭")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def write_message(stream: BinaryIO, message: dict[str, Any]) -> None:
    """把 JSON-RPC 消息编码为 JSON 并写入流（含 flush）。"""
    body = json.dumps(message, ensure_ascii=False).encode("utf-8")
    stream.write(frame_message(body))
    stream.flush()
