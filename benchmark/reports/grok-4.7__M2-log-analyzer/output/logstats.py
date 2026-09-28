"""Parse access logs and report aggregate statistics."""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Iterable

# Common-log shape: the token between ip and user is a literal ident field, always "-".
# Duration may be an integer or a fractional decimal; octets outside 0-255 are rejected.
_LINE_RE = re.compile(
    r"(?P<ip>(?:\d{1,3}\.){3}\d{1,3})"
    r" - "
    r"(?P<user>-|[A-Za-z0-9_]+)"
    r" \[(?P<timestamp>\d{2}/[A-Za-z]{3}/\d{4}:\d{2}:\d{2}:\d{2} [+-]\d{4})\]"
    r' "(?P<method>[A-Z]+) (?P<path>\S+) (?P<protocol>\S+)"'
    r" (?P<status>\d{3})"
    r" (?P<bytes>\d+|-)"
    r" (?P<duration>\d+(?:\.\d+)?)"
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

_STATUS_KEYS = ("2xx", "3xx", "4xx", "5xx", "other")


def _strip_terminator(line: str) -> str:
    if line.endswith("\r\n"):
        return line[:-2]
    if line.endswith(("\n", "\r")):
        return line[:-1]
    return line


def _is_blank(line: str) -> bool:
    return _strip_terminator(line).strip() == ""


def _valid_ipv4(ip: str) -> bool:
    parts = ip.split(".")
    if len(parts) != 4:
        return False
    for part in parts:
        if not part.isdigit():
            return False
        value = int(part)
        if value > 255:
            return False
    return True


def _parse_timestamp(text: str) -> datetime | None:
    try:
        stamp, offset_s = text.rsplit(" ", 1)
        day_s, mon_s, year_hms = stamp.split("/", 2)
        year_s, hour_s, min_s, sec_s = year_hms.split(":")
        sign = 1 if offset_s[0] == "+" else -1
        off_h = int(offset_s[1:3])
        off_m = int(offset_s[3:5])
        if off_m > 59:
            return None
        offset = timedelta(hours=off_h, minutes=off_m) * sign
        return datetime(
            int(year_s),
            _MONTHS[mon_s],
            int(day_s),
            int(hour_s),
            int(min_s),
            int(sec_s),
            tzinfo=timezone(offset),
        )
    except (KeyError, ValueError, IndexError):
        return None


def parse_line(line: str) -> dict | None:
    """Return a record dict, or None when the line is malformed."""
    text = _strip_terminator(line)
    match = _LINE_RE.fullmatch(text)
    if match is None:
        return None
    ip = match.group("ip")
    if not _valid_ipv4(ip):
        return None
    timestamp = _parse_timestamp(match.group("timestamp"))
    if timestamp is None:
        return None
    user = match.group("user")
    bytes_s = match.group("bytes")
    return {
        "ip": ip,
        "user": None if user == "-" else user,
        "timestamp": timestamp,
        "method": match.group("method"),
        "path": match.group("path"),
        "protocol": match.group("protocol"),
        "status": int(match.group("status")),
        "bytes": 0 if bytes_s == "-" else int(bytes_s),
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


def _nearest_rank(sorted_vals: list[float], percentile: int) -> float:
    # Integer ceil(p / 100 * n) avoids binary-float off-by-ones.
    n = len(sorted_vals)
    index = (percentile * n + 99) // 100 - 1
    if index < 0:
        index = 0
    elif index >= n:
        index = n - 1
    return round(sorted_vals[index], 3)


def _duration_stats(durations: list[float]) -> dict:
    if not durations:
        return {"count": 0, "mean": 0.0, "p50": 0.0, "p95": 0.0, "max": 0.0}
    ordered = sorted(durations)
    return {
        "count": len(ordered),
        "mean": round(sum(ordered) / len(ordered), 3),
        "p50": _nearest_rank(ordered, 50),
        "p95": _nearest_rank(ordered, 95),
        "max": round(ordered[-1], 3),
    }


def _top_counts(counter: Counter, key_name: str, top: int) -> list[dict]:
    ranked = sorted(counter.items(), key=lambda item: (-item[1], item[0]))
    if top < 0:
        top = 0
    return [{key_name: name, "count": count} for name, count in ranked[:top]]


def analyze(lines: Iterable[str], top: int = 5) -> dict:
    """Aggregate an iterable of raw log lines into the report structure."""
    lines_total = 0
    lines_malformed = 0
    bytes_total = 0
    status_classes = {key: 0 for key in _STATUS_KEYS}
    methods: Counter[str] = Counter()
    paths: Counter[str] = Counter()
    ips: Counter[str] = Counter()
    durations: list[float] = []

    for line in lines:
        if _is_blank(line):
            continue
        lines_total += 1
        record = parse_line(line)
        if record is None:
            lines_malformed += 1
            continue
        bytes_total += record["bytes"]
        status_classes[_status_class(record["status"])] += 1
        methods[record["method"]] += 1
        paths[record["path"]] += 1
        ips[record["ip"]] += 1
        durations.append(record["duration"])

    return {
        "lines_total": lines_total,
        "lines_parsed": lines_total - lines_malformed,
        "lines_malformed": lines_malformed,
        "bytes_total": bytes_total,
        "status_classes": status_classes,
        "methods": dict(sorted(methods.items())),
        "top_paths": _top_counts(paths, "path", top),
        "top_ips": _top_counts(ips, "ip", top),
        "duration": _duration_stats(durations),
    }


def _positive_top(value: str) -> int:
    try:
        number = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("--top must be an integer") from exc
    if number < 1:
        raise argparse.ArgumentTypeError("--top must be an integer >= 1")
    return number


def _render_table(report: dict) -> str:
    rows = [
        f"lines_total: {report['lines_total']}",
        f"lines_parsed: {report['lines_parsed']}",
        f"lines_malformed: {report['lines_malformed']}",
        f"bytes_total: {report['bytes_total']}",
        "status_classes:",
    ]
    for key, count in report["status_classes"].items():
        rows.append(f"  {key}: {count}")
    rows.append("methods:")
    if report["methods"]:
        for key, count in report["methods"].items():
            rows.append(f"  {key}: {count}")
    else:
        rows.append("  (none)")
    rows.append("top_paths:")
    if report["top_paths"]:
        for item in report["top_paths"]:
            rows.append(f"  {item['path']}: {item['count']}")
    else:
        rows.append("  (none)")
    rows.append("top_ips:")
    if report["top_ips"]:
        for item in report["top_ips"]:
            rows.append(f"  {item['ip']}: {item['count']}")
    else:
        rows.append("  (none)")
    duration = report["duration"]
    rows.append("duration:")
    rows.append(
        f"  count={duration['count']} mean={duration['mean']} "
        f"p50={duration['p50']} p95={duration['p95']} max={duration['max']}"
    )
    return "\n".join(rows) + "\n"


def main(argv: list[str] | None = None) -> int:
    """CLI entry point. Returns the process exit code."""
    parser = argparse.ArgumentParser(prog="logstats.py")
    parser.add_argument("logfile")
    parser.add_argument("--top", type=_positive_top, default=5)
    parser.add_argument("--format", choices=("json", "table"), default="json")
    parser.add_argument("--strict", action="store_true")
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        code = exc.code
        return code if isinstance(code, int) else 2

    try:
        with open(args.logfile, encoding="utf-8") as handle:
            lines = handle.readlines()
    except (OSError, UnicodeError) as exc:
        print(f"error: cannot read {args.logfile}: {exc}", file=sys.stderr)
        return 2

    if args.strict:
        for number, line in enumerate(lines, 1):
            if _is_blank(line):
                continue
            if parse_line(line) is None:
                print(
                    f"malformed line {number}: {_strip_terminator(line)}",
                    file=sys.stderr,
                )
                return 2

    report = analyze(lines, top=args.top)
    if args.format == "json":
        sys.stdout.write(json.dumps(report, indent=2) + "\n")
    else:
        sys.stdout.write(_render_table(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
