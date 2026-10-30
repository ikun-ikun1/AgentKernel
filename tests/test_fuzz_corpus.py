"""G-33：500 条坏 JSON + 100 条非法 MCP 帧的确定性模糊测试。

语料在测试内用固定种子生成（可复现，不依赖外部文件）；要求：
- 解析层对任意输入只返回 dict/None，不抛未捕获异常、不挂起；
- 帧层只返回消息体或抛 MCPFramingError，不抛其他异常、不挂起。
"""

from __future__ import annotations

import random
import time
import warnings
from io import BytesIO

from agentkernel.mcp.framing import MCPFramingError, read_frame
from agentkernel.tools.json_repair import parse_json

JSON_COUNT = 500
FRAME_COUNT = 100
SEED = 20261030
NL = chr(10)
TAB = chr(9)
BS = chr(92)
FENCE = chr(96) * 3
CRLF = bytes((13, 10))
LF = bytes((10,))

BASE_JSON = [
    '{"action": "calculator", "action_input": {"expression": "1+2"}}',
    '{"action": "final_answer", "action_input": "hello"}',
    '{"action": "get_current_time", "action_input": {}}',
    '{"actions": [{"action": "calculator", "action_input": {"expression": "1+1"}}]}',
]

EXPLICIT_JSON = [
    "",
    "not json at all",
    "{}",
    "[]",
    "null",
    "42",
    '"just a string"',
    '{"action": "final_answer", "action_input": "unterminated}',
    '{"action": "final_answer", "action_input": "a' + BS + '"b"}',
    '{"action": "final_answer", "action_input": "emoji 😀 中文"}',
    FENCE + "json" + NL + '{"action": "final_answer", "action_input": "fenced"}' + NL + FENCE,
    '前言 {"action": "final_answer", "action_input": "noise"} 后记',
    '{"action": "final_answer", "action_input": "trailing",}',
    "{'action': 'final_answer', 'action_input': 'single-quoted'}",
    '{"action": "final_answer", "action_input": "dup", "action": "calculator"}',
    '{"action": "final_answer", "action_input": NaN}',
    '{"action": "final_answer", "action_input": Infinity}',
    '{"action": "final_answer", "action_input": -Infinity}',
    '{"action": "final_answer" "action_input": "missing comma"}',
    '{"action": "final_answer", "action_input": "unclosed string}',
    '{"action": "final_answer", "action_input": "backslash ' + BS + BS + '"}',
    '{"action": "final_answer", "action_input": "line' + NL + 'break"}',
    '{"action": "final_answer", "action_input": "tab' + TAB + 'char"}',
    '{"action": "final_answer", "action_input": {"nested": {"nested": {"nested": 1}}}}',
    "{" * 2000 + "}" * 2000,
    '{"action": "final_answer", "action_input": "' + "x" * 10000 + '"}',
    '{"action": "final_answer", "action_input": "}]}"}',
    '{"action": "final_answer", "action_input": "}{"}',
    '{"action": "final_answer", "action_input": "' + BS + 'x41"}',
    '{"action": "final_answer", "action_input": true}',
    '{"action": "final_answer", "action_input": null}',
    '{"action": "final_answer", "action_input": [1,2,3]}',
    '{"action": "final_answer", "action_input": 1.2e999}',
    '{"action": "final_answer", "action_input": 0x10}',
    '{"action": "final_answer", "action_input": "a" /* comment */}',
    "// comment" + NL + '{"action": "final_answer", "action_input": "comment"}',
    '{"action": "final_answer", "action_input": "a",}',
    '{"action": "final_answer", "action_input": "a",,}',
    '{"action": "final_answer", "action_input": "a"]',
    '{"action": "final_answer", "action_input": "a"}}',
    '{{"action": "final_answer", "action_input": "double brace"}}',
    '{"action": "final_answer", "action_input": "deep"}' + "}" * 10,
    '{"action": "final_answer", "action_input": "deep"}' + "{" * 10,
    '{"action": "final_answer", "action_input": "crlf' + chr(13) + NL + '"}',
    '{"action": "final_answer", "action_input": "' + BS + '/slash"}',
]

MUTATION_CHARS = list('{}[]",: ' + BS + NL + TAB + "0123456789abcdef.-+eE")


def _mutate(rng: random.Random, text: str) -> str:
    mode = rng.randrange(8)
    if not text:
        return rng.choice(MUTATION_CHARS)
    i = rng.randrange(len(text))
    if mode == 0:
        return text[:i] + text[i + 1 :]
    if mode == 1:
        return text[:i] + rng.choice(MUTATION_CHARS) + text[i:]
    if mode == 2:
        return text[:i] + rng.choice(MUTATION_CHARS) + text[i + 1 :]
    if mode == 3:
        return text[:i]
    if mode == 4:
        j = min(len(text), i + rng.randrange(1, 20))
        return text[:j] + text[i:j] + text[j:]
    if mode == 5:
        return (
            rng.choice(["", "好的：", FENCE + "json" + NL, "prefix "])
            + text
            + rng.choice(["", " 完", NL + FENCE, "}"])
        )
    if mode == 6:
        j = rng.randrange(len(text))
        chars = list(text)
        chars[i], chars[j] = chars[j], chars[i]
        return "".join(chars)
    return text + rng.choice(MUTATION_CHARS)


def build_json_cases(count: int = JSON_COUNT) -> list[str]:
    seen = set(EXPLICIT_JSON)
    cases = list(EXPLICIT_JSON)
    rng = random.Random(SEED)
    while len(cases) < count:
        text = _mutate(rng, rng.choice(BASE_JSON))
        if text in seen:
            continue
        seen.add(text)
        cases.append(text)
    return cases[:count]


def _frame(body: bytes) -> bytes:
    return b"Content-Length: " + str(len(body)).encode() + CRLF + CRLF + body


def build_frame_cases(count: int = FRAME_COUNT) -> list[bytes]:
    valid = _frame(b'{"jsonrpc":"2.0","id":1,"method":"ping"}')
    explicit = [
        valid,
        b"",
        CRLF,
        b"Content-Length: 0" + CRLF + CRLF,
        b"Content-Length: 5" + CRLF + CRLF + b"hello",
        b"Content-Length: 5" + CRLF + CRLF + b"hel",
        b"Content-Length: 5" + CRLF + CRLF + b"helloextra",
        b"Content-Length: -1" + CRLF + CRLF,
        b"Content-Length: 999999" + CRLF + CRLF,
        b"Content-Length: abc" + CRLF + CRLF,
        b"Content-Length: 1.5" + CRLF + CRLF,
        b"Content-Length: +5" + CRLF + CRLF + b"hello",
        b"Content-Length: 5" + CRLF + CRLF,
        b"Content-Length:5" + LF + LF + b"hello",
        b"Content-Length: 5" + LF + LF + b"hello",
        b"Content-Length: 5" + CRLF + b"X-Test: 1" + CRLF + CRLF + b"hello",
        b"Content-Length: 5" + CRLF + b"Content-Length: 6" + CRLF + CRLF + b"hello",
        b"Content-Length: 5" + CRLF + b"BrokenHeader" + CRLF + CRLF + b"hello",
        b"Content-Length: 5" + CRLF + CRLF + bytes((255, 254, 0, 1, 2)),
        b"Content-Length: 0" + CRLF + CRLF + b"x" * 100,
        b"Content-Length: " + b"9" * 20 + CRLF + CRLF,
        b"X: " + b"y" * 9000 + CRLF + CRLF,
        b"Content-Length: 5" + CRLF + CRLF + b"hello" + CRLF + CRLF,
        b"Content-Length: 5" + CRLF + CRLF + b"hello" + bytes((0,)),
        b"content-length: 5" + CRLF + CRLF + b"hello",
        b"CONTENT-LENGTH: 5" + CRLF + CRLF + b"hello",
    ]
    seen = set(explicit)
    cases = list(explicit)
    rng = random.Random(SEED + 1)
    while len(cases) < count:
        frame = bytearray(valid)
        mode = rng.randrange(5)
        i = rng.randrange(len(frame))
        if mode == 0:
            del frame[i]
        elif mode == 1:
            frame.insert(i, rng.randrange(256))
        elif mode == 2:
            frame[i] = rng.randrange(256)
        elif mode == 3:
            frame = frame[:i]
        else:
            frame.extend(rng.randbytes(rng.randrange(1, 10)))
        candidate = bytes(frame)
        if candidate in seen:
            continue
        seen.add(candidate)
        cases.append(candidate)
    return cases[:count]


def test_bad_json_corpus_500_cases_no_crash() -> None:
    cases = build_json_cases()
    assert len(cases) == JSON_COUNT
    assert len(set(cases)) == JSON_COUNT
    started = time.perf_counter()
    with warnings.catch_warnings():
        # 模糊输入可能触发 ast.literal_eval 对非法转义的 DeprecationWarning，属预期
        warnings.simplefilter("ignore", DeprecationWarning)
        for text in cases:
            result = parse_json(text)
            assert result is None or isinstance(result, dict)
    assert time.perf_counter() - started < 5.0


def test_deep_nesting_degrades_instead_of_recursion_error() -> None:
    assert parse_json("{" * 2000 + "}" * 2000) is None


def test_bad_frames_corpus_100_cases_no_crash() -> None:
    cases = build_frame_cases()
    assert len(cases) == FRAME_COUNT
    assert len(set(cases)) == FRAME_COUNT
    started = time.perf_counter()
    for frame in cases:
        try:
            body = read_frame(BytesIO(frame), max_frame_bytes=4096)
        except MCPFramingError:
            continue
        assert isinstance(body, bytes)
    assert time.perf_counter() - started < 5.0
