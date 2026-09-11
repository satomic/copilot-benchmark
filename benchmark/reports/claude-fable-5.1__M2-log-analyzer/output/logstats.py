"""Access log analyzer: library + CLI."""

from __future__ import annotations

import argparse as _argparse
import json as _json
import math as _math
import re as _re
import sys as _sys
from collections import Counter as _Counter
from datetime import datetime as _datetime
from datetime import timedelta as _timedelta
from datetime import timezone as _timezone
from typing import Iterable as _Iterable

__all__ = ["parse_line", "analyze", "main"]

_LINE_RE = _re.compile(
    r"^(?P<ip>\d{1,3}(?:\.\d{1,3}){3}) - (?P<user>-|\w+) "
    r"\[(?P<ts>\d{2}/[A-Z][a-z]{2}/\d{4}:\d{2}:\d{2}:\d{2} [+-]\d{4})\] "
    r'"(?P<method>[A-Z]+) (?P<path>\S+) (?P<protocol>\S+)" '
    r"(?P<status>\d{3}) (?P<bytes>-|\d+) (?P<duration>\d+(?:\.\d+)?|\.\d+)$"
)

_MONTHS = {
    "Jan": 1, "Feb": 2, "Mar": 3, "Apr": 4, "May": 5, "Jun": 6,
    "Jul": 7, "Aug": 8, "Sep": 9, "Oct": 10, "Nov": 11, "Dec": 12,
}


def _parse_timestamp(text: str) -> _datetime | None:
    date_part, offset = text.split(" ")
    day, mon, rest = date_part.split("/")
    year, hour, minute, second = rest.split(":")
    month = _MONTHS.get(mon)
    if month is None:
        return None
    sign = 1 if offset[0] == "+" else -1
    tz = _timezone(sign * _timedelta(hours=int(offset[1:3]), minutes=int(offset[3:5])))
    try:
        return _datetime(int(year), month, int(day), int(hour), int(minute), int(second), tzinfo=tz)
    except ValueError:
        return None


def parse_line(line: str) -> dict | None:
    """Return a record dict, or None when the line is malformed."""
    m = _LINE_RE.match(line.rstrip("\r\n"))
    if m is None:
        return None
    ts = _parse_timestamp(m["ts"])
    if ts is None:
        return None
    user = m["user"]
    raw_bytes = m["bytes"]
    return {
        "ip": m["ip"],
        "user": None if user == "-" else user,
        "timestamp": ts,
        "method": m["method"],
        "path": m["path"],
        "protocol": m["protocol"],
        "status": int(m["status"]),
        "bytes": 0 if raw_bytes == "-" else int(raw_bytes),
        "duration": float(m["duration"]),
    }


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


def _percentile(sorted_values: list[float], p: float) -> float:
    n = len(sorted_values)
    idx = _math.ceil(p / 100 * n) - 1
    idx = min(max(idx, 0), n - 1)
    return sorted_values[idx]


def _top(_Counter: _Counter, key: str, top: int) -> list[dict]:
    ranked = sorted(_Counter.items(), key=lambda kv: (-kv[1], kv[0]))[:top]
    return [{key: name, "count": count} for name, count in ranked]


def analyze(lines: _Iterable[str], top: int = 5) -> dict:
    """Aggregate an _Iterable of raw log lines into the report structure."""
    lines_total = lines_parsed = lines_malformed = 0
    bytes_total = 0
    status_classes = {"2xx": 0, "3xx": 0, "4xx": 0, "5xx": 0, "other": 0}
    methods: _Counter = _Counter()
    paths: _Counter = _Counter()
    ips: _Counter = _Counter()
    durations: list[float] = []

    for line in lines:
        if not line.strip():
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
        duration = {
            "count": len(durations),
            "mean": round(sum(durations) / len(durations), 3),
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
        "methods": dict(sorted(methods.items())),
        "top_paths": _top(paths, "path", top),
        "top_ips": _top(ips, "ip", top),
        "duration": duration,
    }


def _format_table(report: dict) -> str:
    out = []
    for key in ("lines_total", "lines_parsed", "lines_malformed", "bytes_total"):
        out.append(f"{key:<16}{report[key]}")
    out.append("status_classes")
    for cls, count in report["status_classes"].items():
        out.append(f"  {cls:<8}{count}")
    out.append("methods")
    for method, count in report["methods"].items():
        out.append(f"  {method:<8}{count}")
    out.append("top_paths")
    for entry in report["top_paths"]:
        out.append(f"  {entry['count']:>6}  {entry['path']}")
    out.append("top_ips")
    for entry in report["top_ips"]:
        out.append(f"  {entry['count']:>6}  {entry['ip']}")
    out.append("duration")
    for k, v in report["duration"].items():
        out.append(f"  {k:<8}{v}")
    return "\n".join(out) + "\n"


class _ArgumentParser(_argparse.ArgumentParser):
    # argparse exits with 2 on usage errors and calls _sys.exit; we raise instead so
    # main() can return the code without terminating the interpreter.
    def error(self, message: str) -> None:  # type: ignore[override]
        raise _UsageError(message)


class _UsageError(Exception):
    pass


def _positive_int(text: str) -> int:
    try:
        value = int(text)
    except ValueError:
        raise _argparse.ArgumentTypeError(f"invalid int value: {text!r}")
    if value < 1:
        raise _argparse.ArgumentTypeError("--top must be >= 1")
    return value


def _build_parser() -> _ArgumentParser:
    parser = _ArgumentParser(prog="logstats.py", description="Summarize an access log.")
    parser.add_argument("logfile")
    parser.add_argument("--top", type=_positive_int, default=5)
    parser.add_argument("--format", choices=("json", "table"), default="json")
    parser.add_argument("--strict", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI entry point. Returns the process exit code."""
    parser = _build_parser()
    try:
        args = parser.parse_args(argv)
    except _UsageError as exc:
        print(f"{parser.prog}: error: {exc}", file=_sys.stderr)
        return 2

    try:
        with open(args.logfile, "r", encoding="utf-8", errors="replace") as fh:
            lines = fh.readlines()
    except OSError as exc:
        print(f"{parser.prog}: cannot read {args.logfile!r}: {exc.strerror or exc}", file=_sys.stderr)
        return 2

    if args.strict:
        for number, line in enumerate(lines, start=1):
            if line.strip() and parse_line(line) is None:
                stripped = line.rstrip("\r\n")
                print(f"malformed line {number}: {stripped}", file=_sys.stderr)
                return 2

    report = analyze(lines, top=args.top)
    if args.format == "json":
        _sys.stdout.write(_json.dumps(report, indent=2) + "\n")
    else:
        _sys.stdout.write(_format_table(report))
    return 0


if __name__ == "__main__":
    _sys.exit(main())
