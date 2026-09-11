"""Access log parser and statistics reporter."""

import argparse as _argparse
import datetime as _dt
import json as _json
import math as _math
import re as _re
import sys as _sys
from collections import Counter as _Counter
from typing import Iterable as _Iterable

__all__ = ["analyze", "main", "parse_line"]

_LINE_RE = _re.compile(
    r"(?P<ip>\d{1,3}(?:\.\d{1,3}){3})"
    r" - "
    r"(?P<user>-|\w+)"
    r" \[(?P<timestamp>\d{2}/[A-Za-z]{3}/\d{4}:\d{2}:\d{2}:\d{2} [+-]\d{4})\]"
    r' "(?P<method>[A-Z]+) (?P<path>\S+) (?P<protocol>\S+)"'
    r" (?P<status>\d{3})"
    r" (?P<bytes>-|\d+)"
    r" (?P<duration>\d+(?:\.\d+)?)"
)

_TS_FORMAT = "%d/%b/%Y:%H:%M:%S %z"

_STATUS_CLASSES = ("2xx", "3xx", "4xx", "5xx", "other")


def parse_line(line: str) -> dict | None:
    """Return a record dict, or None when the line is malformed."""
    # Only a trailing line terminator is tolerated; other stray whitespace is malformed.
    stripped = line.rstrip("\n").rstrip("\r")
    match = _LINE_RE.fullmatch(stripped)
    if match is None:
        return None

    try:
        timestamp = _dt.datetime.strptime(match["timestamp"], _TS_FORMAT)
    except ValueError:
        return None

    raw_bytes = match["bytes"]
    user = match["user"]
    return {
        "ip": match["ip"],
        "user": None if user == "-" else user,
        "timestamp": timestamp,
        "method": match["method"],
        "path": match["path"],
        "protocol": match["protocol"],
        "status": int(match["status"]),
        "bytes": 0 if raw_bytes == "-" else int(raw_bytes),
        "duration": float(match["duration"]),
    }


def _is_blank(line: str) -> bool:
    return not line.strip()


def _status_class(status: int) -> str:
    if 200 <= status < 600:
        return f"{status // 100}xx"
    return "other"


def _percentile(sorted_values: list[float], percentile: float) -> float:
    n = len(sorted_values)
    index = _math.ceil(percentile / 100 * n) - 1
    index = min(max(index, 0), n - 1)
    return sorted_values[index]


def _duration_stats(durations: list[float]) -> dict:
    if not durations:
        return {"count": 0, "mean": 0.0, "p50": 0.0, "p95": 0.0, "max": 0.0}
    ordered = sorted(durations)
    return {
        "count": len(ordered),
        "mean": round(sum(ordered) / len(ordered), 3),
        "p50": round(_percentile(ordered, 50), 3),
        "p95": round(_percentile(ordered, 95), 3),
        "max": round(ordered[-1], 3),
    }


def _top(counter: _Counter, key: str, top: int) -> list[dict]:
    ranked = sorted(counter.items(), key=lambda item: (-item[1], item[0]))
    return [{key: name, "count": count} for name, count in ranked[:top]]


def analyze(lines: _Iterable[str], top: int = 5) -> dict:
    """Aggregate an iterable of raw log lines into the report structure."""
    lines_total = 0
    lines_parsed = 0
    lines_malformed = 0
    bytes_total = 0
    status_classes = {name: 0 for name in _STATUS_CLASSES}
    methods: _Counter = _Counter()
    paths: _Counter = _Counter()
    ips: _Counter = _Counter()
    durations: list[float] = []

    for line in lines:
        if _is_blank(line):
            continue
        lines_total += 1
        record = parse_line(line)
        if record is None:
            lines_malformed += 1
            continue
        lines_parsed += 1
        bytes_total += record["bytes"]
        status_classes[_status_class(record["status"])] += 1
        methods[record["method"]] += 1
        paths[record["path"]] += 1
        ips[record["ip"]] += 1
        durations.append(record["duration"])

    return {
        "lines_total": lines_total,
        "lines_parsed": lines_parsed,
        "lines_malformed": lines_malformed,
        "bytes_total": bytes_total,
        "status_classes": status_classes,
        "methods": dict(sorted(methods.items())),
        "top_paths": _top(paths, "path", top),
        "top_ips": _top(ips, "ip", top),
        "duration": _duration_stats(durations),
    }


def _format_table(report: dict) -> str:
    out = [
        f"lines_total: {report['lines_total']}",
        f"lines_parsed: {report['lines_parsed']}",
        f"lines_malformed: {report['lines_malformed']}",
        f"bytes_total: {report['bytes_total']}",
        "status_classes:",
    ]
    for name, count in report["status_classes"].items():
        out.append(f"  {name:<6} {count}")
    out.append("methods:")
    for method, count in report["methods"].items():
        out.append(f"  {method:<8} {count}")
    out.append("top_paths:")
    for entry in report["top_paths"]:
        out.append(f"  {entry['count']:>8}  {entry['path']}")
    out.append("top_ips:")
    for entry in report["top_ips"]:
        out.append(f"  {entry['count']:>8}  {entry['ip']}")
    duration = report["duration"]
    out.append("duration:")
    for name in ("count", "mean", "p50", "p95", "max"):
        out.append(f"  {name:<6} {duration[name]}")
    return "\n".join(out)


def _build_parser() -> _argparse.ArgumentParser:
    parser = _argparse.ArgumentParser(
        prog="logstats.py", description="Analyze an access log."
    )
    parser.add_argument("logfile", help="path to the access log")
    parser.add_argument("--top", type=int, default=5, help="how many paths/IPs to report")
    parser.add_argument("--format", choices=("json", "table"), default="json")
    parser.add_argument("--strict", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI entry point. Returns the process exit code."""
    parser = _build_parser()
    try:
        args = parser.parse_args(_sys.argv[1:] if argv is None else argv)
    except SystemExit as exc:
        return int(exc.code or 0)

    if args.top < 1:
        print("error: --top must be at least 1", file=_sys.stderr)
        return 2

    try:
        with open(args.logfile, "r", encoding="utf-8", errors="replace") as handle:
            lines = handle.readlines()
    except OSError as exc:
        print(f"error: cannot read {args.logfile}: {exc}", file=_sys.stderr)
        return 2

    if args.strict:
        for number, line in enumerate(lines, start=1):
            if _is_blank(line):
                continue
            if parse_line(line) is None:
                stripped = line.rstrip("\n").rstrip("\r")
                print(f"malformed line {number}: {stripped}", file=_sys.stderr)
                return 2

    report = analyze(lines, top=args.top)

    if args.format == "table":
        _sys.stdout.write(_format_table(report) + "\n")
    else:
        _sys.stdout.write(_json.dumps(report, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    _sys.exit(main())
