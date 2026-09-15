"""Access-log parser, aggregator, and CLI."""

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
    r"^"
    r"(?P<ip>\d{1,3}(?:\.\d{1,3}){3})"
    r" - "
    r"(?P<user>-|\w+)"
    r" \["
    r"(?P<timestamp>\d{2}/[A-Za-z]{3}/\d{4}:\d{2}:\d{2}:\d{2} [+-]\d{4})"
    r"\] "
    r'"(?P<method>[A-Z]+) (?P<path>\S+) (?P<protocol>\S+)" '
    r"(?P<status>\d{3}) "
    r"(?P<bytes>-|\d+) "
    r"(?P<duration>\d+(?:\.\d+)?)"
    r"$"
)

_STATUS_KEYS = ("2xx", "3xx", "4xx", "5xx", "other")


def parse_line(line: str) -> dict | None:
    """Return a record dict, or None when the line is malformed."""
    raw = line.rstrip("\r\n")
    match = _LINE_RE.fullmatch(raw)
    if match is None:
        return None
    octets = match.group("ip").split(".")
    if any(int(part) > 255 for part in octets):
        return None
    try:
        timestamp = datetime.strptime(match.group("timestamp"), "%d/%b/%Y:%H:%M:%S %z")
    except ValueError:
        return None
    user_field = match.group("user")
    bytes_field = match.group("bytes")
    return {
        "ip": match.group("ip"),
        "user": None if user_field == "-" else user_field,
        "timestamp": timestamp,
        "method": match.group("method"),
        "path": match.group("path"),
        "protocol": match.group("protocol"),
        "status": int(match.group("status")),
        "bytes": 0 if bytes_field == "-" else int(bytes_field),
        "duration": float(match.group("duration")),
    }


def _status_class(status: int) -> str:
    if 200 <= status <= 299:
        return "2xx"
    if 300 <= status <= 399:
        return "3xx"
    if 400 <= status <= 499:
        return "4xx"
    if 500 <= status <= 599:
        return "5xx"
    return "other"


def _percentile(sorted_vals: list[float], p: float) -> float:
    n = len(sorted_vals)
    if n == 0:
        return 0.0
    index = math.ceil(p / 100.0 * n) - 1
    index = min(max(index, 0), n - 1)
    return sorted_vals[index]


def _top_n(counter: Counter, key_name: str, n: int) -> list[dict]:
    ranked = sorted(counter.items(), key=lambda item: (-item[1], item[0]))
    return [{key_name: key, "count": count} for key, count in ranked[:n]]


def analyze(lines: Iterable[str], top: int = 5) -> dict:
    """Aggregate an iterable of raw log lines into the report structure."""
    lines_total = 0
    lines_parsed = 0
    lines_malformed = 0
    bytes_total = 0
    status_classes = {key: 0 for key in _STATUS_KEYS}
    methods: Counter = Counter()
    paths: Counter = Counter()
    ips: Counter = Counter()
    durations: list[float] = []

    for line in lines:
        if line.strip() == "":
            continue
        lines_total += 1
        rec = parse_line(line)
        if rec is None:
            lines_malformed += 1
            continue
        lines_parsed += 1
        bytes_total += rec["bytes"]
        status_classes[_status_class(rec["status"])] += 1
        methods[rec["method"]] += 1
        paths[rec["path"]] += 1
        ips[rec["ip"]] += 1
        durations.append(rec["duration"])

    if durations:
        durations.sort()
        count = len(durations)
        duration = {
            "count": count,
            "mean": round(sum(durations) / count, 3),
            "p50": round(_percentile(durations, 50), 3),
            "p95": round(_percentile(durations, 95), 3),
            "max": round(durations[-1], 3),
        }
    else:
        duration = {"count": 0, "mean": 0.0, "p50": 0.0, "p95": 0.0, "max": 0.0}

    return {
        "lines_total": lines_total,
        "lines_parsed": lines_parsed,
        "lines_malformed": lines_malformed,
        "bytes_total": bytes_total,
        "status_classes": status_classes,
        "methods": {key: methods[key] for key in sorted(methods)},
        "top_paths": _top_n(paths, "path", top),
        "top_ips": _top_n(ips, "ip", top),
        "duration": duration,
    }


def _format_table(report: dict) -> str:
    lines = [
        f"lines_total {report['lines_total']}",
        f"lines_parsed {report['lines_parsed']}",
        f"lines_malformed {report['lines_malformed']}",
        f"bytes_total {report['bytes_total']}",
        "status_classes",
    ]
    for key in _STATUS_KEYS:
        lines.append(f"  {key} {report['status_classes'][key]}")
    lines.append("methods")
    for method, count in report["methods"].items():
        lines.append(f"  {method} {count}")
    lines.append("top_paths")
    for item in report["top_paths"]:
        lines.append(f"  {item['path']} {item['count']}")
    lines.append("top_ips")
    for item in report["top_ips"]:
        lines.append(f"  {item['ip']} {item['count']}")
    dur = report["duration"]
    lines.append("duration")
    lines.append(f"  count {dur['count']}")
    lines.append(f"  mean {dur['mean']}")
    lines.append(f"  p50 {dur['p50']}")
    lines.append(f"  p95 {dur['p95']}")
    lines.append(f"  max {dur['max']}")
    return "\n".join(lines) + "\n"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="logstats.py")
    parser.add_argument("logfile")
    parser.add_argument("--top", default="5")
    parser.add_argument("--format", choices=("json", "table"), default="json")
    parser.add_argument("--strict", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI entry point. Returns the process exit code."""
    parser = _build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit:
        return 2

    try:
        top = int(args.top)
    except (TypeError, ValueError):
        print("error: --top must be an integer", file=sys.stderr)
        return 2
    if top < 1:
        print("error: --top must be at least 1", file=sys.stderr)
        return 2

    try:
        with open(args.logfile, encoding="utf-8") as handle:
            lines = handle.readlines()
    except OSError as exc:
        print(f"error: cannot read {args.logfile}: {exc}", file=sys.stderr)
        return 2

    if args.strict:
        for number, line in enumerate(lines, start=1):
            if line.strip() == "":
                continue
            if parse_line(line) is None:
                stripped = line.rstrip("\r\n")
                print(f"malformed line {number}: {stripped}", file=sys.stderr)
                return 2

    report = analyze(lines, top=top)
    if args.format == "json":
        sys.stdout.write(json.dumps(report, indent=2) + "\n")
    else:
        sys.stdout.write(_format_table(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
