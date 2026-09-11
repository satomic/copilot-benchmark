"""Parse and aggregate access logs.

Line format::

    <ip> - <user> [<dd/Mon/yyyy:HH:MM:SS ±HHMM>] "<method> <path> <proto>" <status> <bytes> <dur>
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from collections import Counter
from datetime import datetime
from typing import Iterable

_LINE_RE = re.compile(
    r"^(?P<ip>\d{1,3}(?:\.\d{1,3}){3})"
    r" - (?P<user>-|\w+)"
    r" \[(?P<ts>\d{2}/[A-Za-z]{3}/\d{4}:\d{2}:\d{2}:\d{2} [+-]\d{4})\]"
    r' "(?P<method>[A-Z]+) (?P<path>\S+) (?P<proto>\S+)"'
    r" (?P<status>\d{3})"
    r" (?P<bytes>-|\d+)"
    r" (?P<dur>\d+(?:\.\d+)?)$"
)

_TS_FORMAT = "%d/%b/%Y:%H:%M:%S %z"


def parse_line(line: str) -> dict | None:
    """Return a record dict, or None when the line is malformed."""
    m = _LINE_RE.match(line.rstrip("\n").rstrip("\r"))
    if m is None:
        return None
    try:
        timestamp = datetime.strptime(m.group("ts"), _TS_FORMAT)
    except ValueError:
        return None
    raw_bytes = m.group("bytes")
    return {
        "ip": m.group("ip"),
        "user": None if m.group("user") == "-" else m.group("user"),
        "timestamp": timestamp,
        "method": m.group("method"),
        "path": m.group("path"),
        "protocol": m.group("proto"),
        "status": int(m.group("status")),
        "bytes": 0 if raw_bytes == "-" else int(raw_bytes),
        "duration": float(m.group("dur")),
    }


def analyze(lines: Iterable[str], top: int = 5) -> dict:
    """Aggregate raw log lines into the report structure."""
    total = parsed = malformed = 0
    bytes_total = 0
    classes = {"2xx": 0, "3xx": 0, "4xx": 0, "5xx": 0, "other": 0}
    methods: Counter[str] = Counter()
    paths: Counter[str] = Counter()
    ips: Counter[str] = Counter()
    durations: list[float] = []

    for raw in lines:
        if not raw.strip():
            continue
        total += 1
        record = parse_line(raw)
        if record is None:
            malformed += 1
            continue
        parsed += 1
        bytes_total += record["bytes"]
        classes[_status_class(record["status"])] += 1
        methods[record["method"]] += 1
        paths[record["path"]] += 1
        ips[record["ip"]] += 1
        durations.append(record["duration"])

    return {
        "lines_total": total,
        "lines_parsed": parsed,
        "lines_malformed": malformed,
        "bytes_total": bytes_total,
        "status_classes": classes,
        "methods": dict(sorted(methods.items())),
        "top_paths": [
            {"path": key, "count": count} for key, count in _rank(paths, top)
        ],
        "top_ips": [{"ip": key, "count": count} for key, count in _rank(ips, top)],
        "duration": _duration_summary(durations),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="logstats", description="Summarize an access log.")
    parser.add_argument("logfile")
    parser.add_argument("--top", type=_positive_int, default=5)
    parser.add_argument("--format", choices=("json", "table"), default="json")
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args(argv)

    try:
        with open(args.logfile, "r", encoding="utf-8", errors="replace") as fh:
            raw_lines = fh.read().splitlines()
    except OSError as exc:
        print(f"cannot read {args.logfile}: {exc}", file=sys.stderr)
        return 2

    if args.strict:
        for number, raw in enumerate(raw_lines, start=1):
            if not raw.strip():
                continue
            if parse_line(raw) is None:
                print(f"malformed line {number}: {raw}", file=sys.stderr)
                return 2

    report = analyze(raw_lines, top=args.top)
    if args.format == "json":
        sys.stdout.write(json.dumps(report, indent=2) + "\n")
    else:
        sys.stdout.write(_render_table(report))
    return 0


# ----------------------------------------------------------------- internals --


def _status_class(status: int) -> str:
    if 200 <= status < 300:
        return "2xx"
    if 300 <= status < 400:
        return "3xx"
    if 400 <= status < 500:
        return "4xx"
    if 500 <= status < 600:
        return "5xx"
    return "other"


def _rank(counter: Counter, top: int) -> list[tuple[str, int]]:
    return sorted(counter.items(), key=lambda kv: (-kv[1], kv[0]))[:top]


def _percentile(sorted_values: list[float], pct: float) -> float:
    if not sorted_values:
        return 0.0
    index = math.ceil(pct / 100 * len(sorted_values)) - 1
    index = max(0, min(index, len(sorted_values) - 1))
    return sorted_values[index]


def _duration_summary(values: list[float]) -> dict:
    if not values:
        return {"count": 0, "mean": 0.0, "p50": 0.0, "p95": 0.0, "max": 0.0}
    ordered = sorted(values)
    return {
        "count": len(ordered),
        "mean": round(sum(ordered) / len(ordered), 3),
        "p50": round(_percentile(ordered, 50), 3),
        "p95": round(_percentile(ordered, 95), 3),
        "max": round(ordered[-1], 3),
    }


def _positive_int(raw: str) -> int:
    value = int(raw)
    if value < 1:
        raise argparse.ArgumentTypeError("must be >= 1")
    return value


def _render_table(report: dict) -> str:
    out = [
        f"lines_total      {report['lines_total']}",
        f"lines_parsed     {report['lines_parsed']}",
        f"lines_malformed  {report['lines_malformed']}",
        f"bytes_total      {report['bytes_total']}",
        "",
        "status_classes",
    ]
    for key, count in report["status_classes"].items():
        out.append(f"  {key:<6} {count}")
    out.append("")
    out.append("methods")
    for key, count in report["methods"].items():
        out.append(f"  {key:<8} {count}")
    out.append("")
    out.append("top_paths")
    for row in report["top_paths"]:
        out.append(f"  {row['count']:>6}  {row['path']}")
    out.append("")
    out.append("top_ips")
    for row in report["top_ips"]:
        out.append(f"  {row['count']:>6}  {row['ip']}")
    out.append("")
    dur = report["duration"]
    out.append(
        "duration  count={count} mean={mean} p50={p50} p95={p95} max={max}".format(**dur)
    )
    return "\n".join(out) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
