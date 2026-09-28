"""Parse access logs and report aggregate request statistics."""

from __future__ import annotations

import argparse as _argparse
from collections import Counter as _Counter
from datetime import datetime as _datetime, timedelta as _timedelta, timezone as _timezone
import json as _json
import math as _math
import re as _re
import sys as _sys
from typing import Iterable as _Iterable, TextIO as _TextIO


_LINE_RE = _re.compile(
    r'(?P<ip>\S+) - (?P<user>-|\w+) '
    r'\[(?P<timestamp>[0-9]{2}/[A-Za-z]{3}/[0-9]{4}:[0-9]{2}:[0-9]{2}:[0-9]{2} [+-][0-9]{4})\] '
    r'"(?P<method>[A-Z]+) (?P<path>[^"\s]+) (?P<protocol>[^"\s]+)" '
    r'(?P<status>[0-9]{3}) (?P<bytes>[0-9]+|-) (?P<duration>[0-9]+(?:\.[0-9]+)?)'
)
_IPV4_RE = _re.compile(
    r'(?:(?:25[0-5]|2[0-4][0-9]|1[0-9]{2}|[1-9]?[0-9])\.){3}'
    r'(?:25[0-5]|2[0-4][0-9]|1[0-9]{2}|[1-9]?[0-9])'
)
_MONTHS = {
    "Jan": 1,
    "Feb": 2,
    "Mar": 3,
    "Apr": 4,
    "May": 5,
    "Jun": 6,
    "Jul": 7,
    "Aug": 8,
    "Sep": 9,
    "Oct": 10,
    "Nov": 11,
    "Dec": 12,
}


def parse_line(line: str) -> dict | None:
    """Return a parsed access-log record, or None if the entire line is invalid."""
    if line.endswith("\r\n"):
        line = line[:-2]
    elif line.endswith(("\n", "\r")):
        line = line[:-1]

    match = _LINE_RE.fullmatch(line)
    if match is None:
        return None

    fields = match.groupdict()
    if _IPV4_RE.fullmatch(fields["ip"]) is None:
        return None

    timestamp_match = _re.fullmatch(
        r"([0-9]{2})/([A-Za-z]{3})/([0-9]{4}):([0-9]{2}):([0-9]{2}):([0-9]{2}) ([+-])([0-9]{2})([0-9]{2})",
        fields["timestamp"],
    )
    if timestamp_match is None:
        return None
    day, month_name, year, hour, minute, second, sign, offset_hour, offset_minute = (
        timestamp_match.groups()
    )
    month = _MONTHS.get(month_name)
    if month is None:
        return None
    offset_hours = int(offset_hour)
    offset_minutes = int(offset_minute)
    if offset_hours > 23 or offset_minutes > 59:
        return None
    offset = _timedelta(hours=offset_hours, minutes=offset_minutes)
    if sign == "-":
        offset = -offset
    try:
        timestamp = _datetime(
            int(year), month, int(day), int(hour), int(minute), int(second),
            tzinfo=_timezone(offset),
        )
    except ValueError:
        return None
    duration = float(fields["duration"])
    if not _math.isfinite(duration):
        return None

    return {
        "ip": fields["ip"],
        "user": None if fields["user"] == "-" else fields["user"],
        "timestamp": timestamp,
        "method": fields["method"],
        "path": fields["path"],
        "protocol": fields["protocol"],
        "status": int(fields["status"]),
        "bytes": 0 if fields["bytes"] == "-" else int(fields["bytes"]),
        "duration": duration,
    }


def analyze(lines: _Iterable[str], top: int = 5) -> dict:
    """Aggregate raw log lines into the documented report structure."""
    if isinstance(top, bool) or not isinstance(top, int) or top < 1:
        raise ValueError("top must be an integer greater than or equal to 1")

    lines_total = 0
    lines_parsed = 0
    lines_malformed = 0
    bytes_total = 0
    status_classes = {"2xx": 0, "3xx": 0, "4xx": 0, "5xx": 0, "other": 0}
    methods: _Counter[str] = _Counter()
    paths: _Counter[str] = _Counter()
    ips: _Counter[str] = _Counter()
    durations: list[float] = []

    for line in lines:
        if not line.strip():
            continue
        lines_total += 1
        record = parse_line(line)
        if record is None:
            lines_malformed += 1
            continue

        lines_parsed += 1
        bytes_total += record["bytes"]
        status = record["status"]
        status_class = f"{status // 100}xx"
        if status_class not in status_classes or status < 200 or status >= 600:
            status_class = "other"
        status_classes[status_class] += 1
        methods[record["method"]] += 1
        paths[record["path"]] += 1
        ips[record["ip"]] += 1
        durations.append(record["duration"])

    if durations:
        sorted_durations = sorted(durations)

        def percentile(percent: int) -> float:
            index = _math.ceil(percent / 100 * len(sorted_durations)) - 1
            index = min(max(index, 0), len(sorted_durations) - 1)
            return sorted_durations[index]

        duration_report = {
            "count": len(durations),
            "mean": round(sum(durations) / len(durations), 3),
            "p50": round(percentile(50), 3),
            "p95": round(percentile(95), 3),
            "max": round(max(durations), 3),
        }
    else:
        duration_report = {
            "count": 0,
            "mean": 0.0,
            "p50": 0.0,
            "p95": 0.0,
            "max": 0.0,
        }

    return {
        "lines_total": lines_total,
        "lines_parsed": lines_parsed,
        "lines_malformed": lines_malformed,
        "bytes_total": bytes_total,
        "status_classes": status_classes,
        "methods": dict(sorted(methods.items())),
        "top_paths": [
            {"path": path, "count": count}
            for path, count in sorted(paths.items(), key=lambda item: (-item[1], item[0]))[:top]
        ],
        "top_ips": [
            {"ip": ip, "count": count}
            for ip, count in sorted(ips.items(), key=lambda item: (-item[1], item[0]))[:top]
        ],
        "duration": duration_report,
    }


class _MalformedLogLine(Exception):
    def __init__(self, number: int, line: str) -> None:
        self.number = number
        self.line = line.rstrip("\r\n")


def _strict_lines(lines: _Iterable[str]) -> _Iterable[str]:
    for number, line in enumerate(lines, start=1):
        if line.strip() and parse_line(line) is None:
            raise _MalformedLogLine(number, line)
        yield line


def _write_table(report: dict, stream: _TextIO) -> None:
    print(f"lines_total: {report['lines_total']}", file=stream)
    print(f"lines_parsed: {report['lines_parsed']}", file=stream)
    print(f"lines_malformed: {report['lines_malformed']}", file=stream)
    print(f"bytes_total: {report['bytes_total']}", file=stream)
    print(f"status_classes: {report['status_classes']}", file=stream)
    print(f"methods: {report['methods']}", file=stream)
    print("top_paths:", file=stream)
    for entry in report["top_paths"]:
        print(f"  {entry['path']}: {entry['count']}", file=stream)
    print("top_ips:", file=stream)
    for entry in report["top_ips"]:
        print(f"  {entry['ip']}: {entry['count']}", file=stream)
    print(f"duration: {report['duration']}", file=stream)


def main(argv: list[str] | None = None) -> int:
    """Run the command-line interface and return its exit code."""
    parser = _argparse.ArgumentParser(description="Summarize an access log.")
    parser.add_argument("logfile")
    parser.add_argument("--top", type=int, default=5)
    parser.add_argument("--format", choices=("json", "table"), default="json")
    parser.add_argument("--strict", action="store_true")
    try:
        args = parser.parse_args(argv)
    except SystemExit as error:
        return int(error.code)

    if args.top < 1:
        parser.print_usage(_sys.stderr)
        print("logstats.py: error: --top must be at least 1", file=_sys.stderr)
        return 2

    try:
        with open(args.logfile, "r", encoding="utf-8") as logfile:
            report = analyze(
                _strict_lines(logfile) if args.strict else logfile,
                top=args.top,
            )
    except _MalformedLogLine as error:
        print(f"malformed line {error.number}: {error.line}", file=_sys.stderr)
        return 2
    except (OSError, UnicodeError) as error:
        print(f"cannot read {args.logfile}: {error}", file=_sys.stderr)
        return 2

    if args.format == "json":
        _sys.stdout.write(_json.dumps(report, indent=2) + "\n")
    else:
        _write_table(report, _sys.stdout)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
