"""Access log analyzer: library and command-line tool (standard library only)."""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import math
import re
import sys
from collections import Counter
from typing import Iterable

_LINE_RE = re.compile(
    r"(?P<ip>\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})"
    r" - (?P<user>-|\w+)"
    r" \[(?P<ts>[^\]]+)\]"
    r' "(?P<method>[A-Z]+) (?P<path>\S+) (?P<protocol>\S+)"'
    r" (?P<status>\d{3})"
    r" (?P<bytes>\d+|-)"
    r" (?P<duration>\d+(?:\.\d+)?)"
)

_TS_RE = re.compile(
    r"(?P<day>\d{2})/(?P<mon>[A-Za-z]{3})/(?P<year>\d{4})"
    r":(?P<h>\d{2}):(?P<m>\d{2}):(?P<s>\d{2})"
    r" (?P<sign>[+-])(?P<oh>\d{2})(?P<om>\d{2})"
)

_MONTHS = {
    name: i
    for i, name in enumerate(
        ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
         "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"],
        start=1,
    )
}

_STATUS_KEYS = ("2xx", "3xx", "4xx", "5xx", "other")


def _parse_ip(text: str) -> bool:
    # Each octet must be 0-255; the regex only checks the digit shape.
    return all(int(octet) <= 255 for octet in text.split("."))


def _parse_timestamp(text: str) -> _dt.datetime | None:
    m = _TS_RE.fullmatch(text)
    if m is None or m.group("mon") not in _MONTHS:
        return None
    if int(m.group("om")) >= 60:
        return None
    offset = _dt.timedelta(hours=int(m.group("oh")), minutes=int(m.group("om")))
    if m.group("sign") == "-":
        offset = -offset
    tz = _dt.timezone(offset)
    try:
        return _dt.datetime(
            int(m.group("year")), _MONTHS[m.group("mon")], int(m.group("day")),
            int(m.group("h")), int(m.group("m")), int(m.group("s")), tzinfo=tz,
        )
    except ValueError:  # e.g. day 31 in February, hour 24
        return None


def parse_line(line: str) -> dict | None:
    """Return a record dict, or None when the line is malformed."""
    # Only line terminators are stripped; other whitespace makes the line malformed.
    text = line.rstrip("\r\n")
    m = _LINE_RE.fullmatch(text)
    if m is None or not _parse_ip(m.group("ip")):
        return None
    timestamp = _parse_timestamp(m.group("ts"))
    if timestamp is None:
        return None
    user = m.group("user")
    raw_bytes = m.group("bytes")
    # Decision: a '-' byte count means no body, so it is recorded as 0.
    return {
        "ip": m.group("ip"),
        "user": None if user == "-" else user,
        "timestamp": timestamp,
        "method": m.group("method"),
        "path": m.group("path"),
        "protocol": m.group("protocol"),
        "status": int(m.group("status")),
        "bytes": 0 if raw_bytes == "-" else int(raw_bytes),
        "duration": float(m.group("duration")),
    }


def _percentile(sorted_values: list[float], p: int) -> float:
    """Nearest-rank percentile over an ascending list (non-empty)."""
    n = len(sorted_values)
    index = math.ceil(p * n / 100) - 1  # integer arithmetic avoids float error
    return sorted_values[min(max(index, 0), n - 1)]


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


def analyze(lines: Iterable[str], top: int = 5) -> dict:
    """Aggregate an iterable of raw log lines into the report structure."""
    lines_total = 0
    lines_parsed = 0
    bytes_total = 0
    status_counts = dict.fromkeys(_STATUS_KEYS, 0)
    methods: Counter[str] = Counter()
    paths: Counter[str] = Counter()
    ips: Counter[str] = Counter()
    durations: list[float] = []

    for line in lines:
        if not line.strip():
            continue  # blank lines are not counted at all
        lines_total += 1
        rec = parse_line(line)
        if rec is None:
            continue
        lines_parsed += 1
        bytes_total += rec["bytes"]
        status_counts[_status_class(rec["status"])] += 1
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

    def _top(counter: Counter, key: str) -> list[dict]:
        ranked = sorted(counter.items(), key=lambda kv: (-kv[1], kv[0]))
        return [{key: name, "count": count} for name, count in ranked[:top]]

    return {
        "lines_total": lines_total,
        "lines_parsed": lines_parsed,
        "lines_malformed": lines_total - lines_parsed,
        "bytes_total": bytes_total,
        "status_classes": status_counts,
        "methods": {m: methods[m] for m in sorted(methods)},
        "top_paths": _top(paths, "path"),
        "top_ips": _top(ips, "ip"),
        "duration": duration,
    }


def _format_table(report: dict) -> str:
    out = [
        f"lines_total      {report['lines_total']}",
        f"lines_parsed     {report['lines_parsed']}",
        f"lines_malformed  {report['lines_malformed']}",
        f"bytes_total      {report['bytes_total']}",
        "",
        "status_classes:",
    ]
    out += [f"  {k:<6} {v}" for k, v in report["status_classes"].items()]
    out += ["", "methods:"]
    out += [f"  {k:<8} {v}" for k, v in report["methods"].items()] or ["  (none)"]
    out += ["", "top_paths:"]
    out += [f"  {e['count']:<6} {e['path']}" for e in report["top_paths"]] or ["  (none)"]
    out += ["", "top_ips:"]
    out += [f"  {e['count']:<6} {e['ip']}" for e in report["top_ips"]] or ["  (none)"]
    d = report["duration"]
    out += [
        "",
        "duration:",
        f"  count {d['count']}  mean {d['mean']}  p50 {d['p50']}  "
        f"p95 {d['p95']}  max {d['max']}",
    ]
    return "\n".join(out) + "\n"


def _positive_int(value: str) -> int:
    try:
        n = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"invalid integer: {value!r}")
    if n < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return n


def main(argv: list[str] | None = None) -> int:
    """CLI entry point. Returns the process exit code."""
    parser = argparse.ArgumentParser(description="Summarise an access log.")
    parser.add_argument("logfile")
    parser.add_argument("--top", type=_positive_int, default=5)
    parser.add_argument("--format", choices=["json", "table"], default="json")
    parser.add_argument("--strict", action="store_true",
                        help="fail on the first malformed line")
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:  # argparse reports usage errors via SystemExit
        return int(exc.code) if isinstance(exc.code, int) else 2

    try:
        with open(args.logfile, encoding="utf-8", errors="replace") as fh:
            lines = fh.readlines()
    except OSError as exc:
        print(f"error: cannot read {args.logfile}: {exc.strerror or exc}", file=sys.stderr)
        return 2

    if args.strict:
        for number, line in enumerate(lines, start=1):
            if line.strip() and parse_line(line) is None:
                text = line.rstrip("\r\n")
                print(f"malformed line {number}: {text}", file=sys.stderr)
                return 2

    report = analyze(lines, top=args.top)
    if args.format == "json":
        sys.stdout.write(json.dumps(report, indent=2) + "\n")
    else:
        sys.stdout.write(_format_table(report))
    return 0


if __name__ == "__main__":
    sys.exit(main())
