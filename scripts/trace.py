"""按 trace_id 打印 span 树（P0-4b / G-10 的本地替代）。

用法：
    python scripts/trace.py --log /tmp/x.jsonl            # 打印最后一条 trace
    python scripts/trace.py --log /tmp/x.jsonl --trace-id <id>
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def load(path: Path) -> list[dict]:
    events: list[dict] = []
    if not path.exists():
        return events
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return events


def render(events: list[dict], trace_id: str) -> str:
    spans = [e for e in events if e.get("trace_id") == trace_id and e.get("span")]
    if not spans:
        return f"trace {trace_id}: 没有 span 事件"
    children: dict[str | None, list[dict]] = {}
    for span in spans:
        children.setdefault(span["span"].get("parent_id"), []).append(span)

    lines = [f"trace {trace_id}（{len(spans)} spans）"]

    def walk(parent: str | None, depth: int) -> None:
        for span in sorted(children.get(parent, []), key=lambda e: e.get("ts", "")):
            info = span["span"]
            status = "ok" if span.get("success") else f"fail:{span.get('error_type')}"
            kind = span.get("tool_name") or span.get("event")
            lines.append(
                f"{'  ' * depth}- {info.get('name')} [{kind}] "
                f"{span.get('latency_ms')}ms {status} span={info.get('id')}"
            )
            walk(info.get("id"), depth + 1)

    walk(None, 0)
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="打印 trace 的 span 树")
    parser.add_argument("--log", required=True, help="JSONL 日志路径")
    parser.add_argument("--trace-id", default=None, help="默认取最后一条 trace")
    args = parser.parse_args()
    events = load(Path(args.log).expanduser())
    trace_id = args.trace_id
    if trace_id is None:
        for event in reversed(events):
            if event.get("trace_id"):
                trace_id = event["trace_id"]
                break
    if trace_id is None:
        print("没有找到 trace_id")
        return
    print(render(events, trace_id))


if __name__ == "__main__":
    main()
