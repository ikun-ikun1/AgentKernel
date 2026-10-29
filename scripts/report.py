"""从 JSONL 运行日志生成 SLO 周报（P0-4 的 make report）。

用法：
    python scripts/report.py                     # 读 AGENTKERNEL_LOG 或 ~/.agentkernel/logs/agentkernel.jsonl
    python scripts/report.py --log /tmp/x.jsonl --out docs/reports

只做聚合，不改业务；没有日志时也生成一份「无数据」报告，退出码 0。
"""

from __future__ import annotations

import argparse
import json
import os
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path


def _percentile(values: list[float], pct: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, round((pct / 100) * (len(ordered) - 1)))
    return ordered[index]


def load_events(path: Path) -> tuple[list[dict], int]:
    events: list[dict] = []
    malformed = 0
    if not path.exists():
        return events, malformed
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            malformed += 1
    return events, malformed


def summarize(events: list[dict]) -> dict:
    turns = [e for e in events if e.get("event") == "turn"]
    tools = [e for e in events if e.get("event") == "tool"]
    failures = [e for e in turns if not e.get("success", False)]
    latencies = [
        float(e["latency_ms"]) for e in turns if isinstance(e.get("latency_ms"), (int, float))
    ]
    tool_latencies = [
        float(e["latency_ms"]) for e in tools if isinstance(e.get("latency_ms"), (int, float))
    ]
    tokens_in = sum((e.get("tokens") or {}).get("in", 0) for e in turns if e.get("tokens"))
    tokens_out = sum((e.get("tokens") or {}).get("out", 0) for e in turns if e.get("tokens"))
    cost = sum(float(e["cost_usd"]) for e in turns if isinstance(e.get("cost_usd"), (int, float)))
    unknown_cost = sum(1 for e in turns if e.get("cost_usd") is None and e.get("tokens"))
    return {
        "turns": len(turns),
        "success_rate": (len(turns) - len(failures)) / len(turns) if turns else None,
        "error_types": Counter(e.get("error_type") or "none" for e in failures).most_common(5),
        "latency_p50": _percentile(latencies, 50),
        "latency_p95": _percentile(latencies, 95),
        "tool_calls": len(tools),
        "tool_errors": sum(1 for e in tools if not e.get("success", False)),
        "tool_latency_p95": _percentile(tool_latencies, 95),
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "cost_usd": round(cost, 6),
        "cost_unknown_turns": unknown_cost,
        "models": Counter(e.get("model") or "unknown" for e in turns).most_common(5),
        "pricing_versions": sorted(
            {str(e.get("pricing_table_version")) for e in events if e.get("pricing_table_version")}
        ),
    }


def update_index(out_dir: Path, week: str, summary: dict) -> Path:
    """维护 docs/reports/index.md：每周一行，便于一眼看趋势。"""
    index = out_dir / "index.md"
    rows: dict[str, list[str]] = {}
    if index.exists():
        for line in index.read_text(encoding="utf-8").splitlines():
            if not line.startswith("| ") or line.startswith("| 周 "):
                continue
            cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
            if len(cells) == 5 and cells[0] and cells[0] != "---":
                rows[cells[0]] = cells
    success = summary["success_rate"]
    rows[week] = [
        week,
        str(summary["turns"]),
        "n/a" if success is None else f"{success:.2%}",
        "n/a" if summary["latency_p95"] is None else f"{summary['latency_p95']}ms",
        f"{summary['cost_usd']}",
    ]
    lines = [
        "# SLO 周报索引",
        "",
        "| 周 | turn 数 | 成功率 | p95 | 成本(USD) |",
        "|---|---|---|---|---|",
    ]
    for key in sorted(rows, reverse=True):
        lines.append("| " + " | ".join(rows[key]) + " |")
    index.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return index


def render(week: str, path: Path, summary: dict, malformed: int) -> str:
    def fmt(value: object, suffix: str = "") -> str:
        return "n/a" if value is None else f"{value}{suffix}"

    success = summary["success_rate"]
    success_text = "n/a" if success is None else f"{success:.2%}"
    lines = [
        f"# SLO 周报 · {week}",
        "",
        f"- 生成时间：{datetime.now(UTC).isoformat(timespec='seconds')}",
        f"- 日志：{path}",
        f"- 解析失败行：{malformed}",
        "",
        "| 指标 | 值 | 目标 |",
        "|---|---|---|",
        f"| turn 数 | {summary['turns']} | — |",
        f"| 成功率 | {success_text} | ≥ 98%（S1） |",
        f"| turn 延迟 p50 / p95 | {fmt(summary['latency_p50'], 'ms')} / {fmt(summary['latency_p95'], 'ms')} | mock p95 ≤ 300ms / live ≤ 12s（S4） |",
        f"| 工具调用 / 失败 | {summary['tool_calls']} / {summary['tool_errors']} | 失败可解释（S3） |",
        f"| 工具延迟 p95 | {fmt(summary['tool_latency_p95'], 'ms')} | — |",
        f"| tokens in / out | {summary['tokens_in']} / {summary['tokens_out']} | 单轮 ≤ 8k in / 2k out（S8） |",
        f"| 成本合计（USD） | {summary['cost_usd']} | 月度 ≤ 5 USD（S8） |",
        f"| 成本未知的 turn | {summary['cost_unknown_turns']} | 0（未知模型需补定价） |",
        "",
        f"- 失败类型 Top：{summary['error_types'] or '无'}",
        f"- 模型分布：{summary['models'] or '无'}",
        f"- 定价表版本：{summary['pricing_versions'] or '无'}",
        "",
        "> 由 make report 生成；字段口径见 docs/production-standard.md 第 4.2 节。",
    ]
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="生成 AgentKernel SLO 周报")
    parser.add_argument("--log", default=None, help="JSONL 日志路径")
    parser.add_argument("--out", default="docs/reports", help="输出目录")
    parser.add_argument("--week", default=None, help="周标识，默认当前 ISO 年-周")
    args = parser.parse_args()

    log_path = Path(
        args.log or os.environ.get("AGENTKERNEL_LOG") or "~/.agentkernel/logs/agentkernel.jsonl"
    ).expanduser()
    week = args.week or datetime.now(UTC).strftime("%G-W%V")
    events, malformed = load_events(log_path)
    summary = summarize(events)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{week}.md"
    out_path.write_text(render(week, log_path, summary, malformed), encoding="utf-8")
    index_path = update_index(out_dir, week, summary)
    print(f"报告已写入 {out_path}（索引：{index_path}）")
    print(
        f"turns={summary['turns']} success={summary['success_rate']} "
        f"p95={summary['latency_p95']}ms cost_usd={summary['cost_usd']}"
    )


if __name__ == "__main__":
    main()
