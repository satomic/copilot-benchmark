from collections import Counter as _Counter
from datetime import datetime as _datetime, timedelta as _timedelta, timezone as _timezone
import argparse as _argparse
import ipaddress as _ipaddress
import json as _json
import math as _math
import re as _re
import sys as _sys
from typing import Iterable as _Iterable

__all__ = ["parse_line", "analyze", "main"]

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

_LINE_RE = _re.compile(
    r"^(\d{1,3}(?:\.\d{1,3}){3}) - (-|\w+) "
    r"\[(\d{2})/([A-Za-z]{3})/(\d{4}):(\d{2}):(\d{2}):(\d{2}) ([+-]\d{4})\] "
    r'"([A-Z]+) ([^\s"]+) ([^\s"]+)" '
    r"(\d{3}) (-|\d+) (\d+(?:\.\d+)?)$"
)


def _parse_timestamp(
    day_s: str,
    mon_s: str,
    year_s: str,
    hour_s: str,
    min_s: str,
    sec_s: str,
    tz_s: str,
) -> _datetime | None:
    month = _MONTHS.get(mon_s)
    if month is None:
        return None
    tz_sign = 1 if tz_s[0] == "+" else -1
    tz_hours = int(tz_s[1:3])
    tz_mins = int(tz_s[3:5])
    if tz_hours > 23 or tz_mins > 59:
        return None
    offset = _timedelta(minutes=tz_sign * (tz_hours * 60 + tz_mins))
    try:
        return _datetime(
            int(year_s),
            month,
            int(day_s),
            int(hour_s),
            int(min_s),
            int(sec_s),
            tzinfo=_timezone(offset),
        )
    except ValueError:
        return None


def parse_line(line: str) -> dict | None:
    """Return a record dict, or None when the line is malformed."""
    if not isinstance(line, str):
        return None
    cleaned = line.rstrip("\r\n")
    match = _LINE_RE.match(cleaned)
    if match is None:
        return None

    (
        ip_s,
        user_s,
        day_s,
        mon_s,
        year_s,
        hour_s,
        min_s,
        sec_s,
        tz_s,
        method_s,
        path_s,
        proto_s,
        status_s,
        bytes_s,
        duration_s,
    ) = match.groups()

    try:
        _ipaddress.IPv4Address(ip_s)
    except ValueError:
        return None

    ts = _parse_timestamp(day_s, mon_s, year_s, hour_s, min_s, sec_s, tz_s)
    if ts is None:
        return None

    duration = float(duration_s)
    if not _math.isfinite(duration) or duration < 0.0:
        return None

    return {
        "ip": ip_s,
        "user": None if user_s == "-" else user_s,
        "timestamp": ts,
        "method": method_s,
        "path": path_s,
        "protocol": proto_s,
        "status": int(status_s),
        "bytes": 0 if bytes_s == "-" else int(bytes_s),
        "duration": duration,
    }


def _percentile(sorted_vals: list[float], p: float) -> float:
    n = len(sorted_vals)
    if n == 0:
        return 0.0
    idx = _math.ceil(p / 100.0 * n) - 1
    idx = max(0, min(n - 1, idx))
    return sorted_vals[idx]


def analyze(lines: _Iterable[str], top: int = 5) -> dict:
    """Aggregate an iterable of raw log lines into the report structure."""
    lines_total = 0
    lines_parsed = 0
    lines_malformed = 0
    bytes_total = 0
    status_classes = {"2xx": 0, "3xx": 0, "4xx": 0, "5xx": 0, "other": 0}
    methods_counter: _Counter[str] = _Counter()
    paths_counter: _Counter[str] = _Counter()
    ips_counter: _Counter[str] = _Counter()
    durations: list[float] = []

    for raw_line in lines:
        if not raw_line.strip():
            continue
        lines_total += 1
        rec = parse_line(raw_line)
        if rec is None:
            lines_malformed += 1
            continue

        lines_parsed += 1
        bytes_total += rec["bytes"]

        status = rec["status"]
        if 200 <= status < 300:
            status_classes["2xx"] += 1
        elif 300 <= status < 400:
            status_classes["3xx"] += 1
        elif 400 <= status < 500:
            status_classes["4xx"] += 1
        elif 500 <= status < 600:
            status_classes["5xx"] += 1
        else:
            status_classes["other"] += 1

        methods_counter[rec["method"]] += 1
        paths_counter[rec["path"]] += 1
        ips_counter[rec["ip"]] += 1
        durations.append(rec["duration"])

    top_n = max(0, top)
    top_paths = [
        {"path": path, "count": count}
        for path, count in sorted(paths_counter.items(), key=lambda kv: (-kv[1], kv[0]))[:top_n]
    ]
    top_ips = [
        {"ip": ip, "count": count}
        for ip, count in sorted(ips_counter.items(), key=lambda kv: (-kv[1], kv[0]))[:top_n]
    ]

    if durations:
        durations.sort()
        count = len(durations)
        mean_val = round(sum(durations) / count, 3)
        p50_val = round(_percentile(durations, 50), 3)
        p95_val = round(_percentile(durations, 95), 3)
        max_val = round(durations[-1], 3)
    else:
        count = 0
        mean_val = 0.0
        p50_val = 0.0
        p95_val = 0.0
        max_val = 0.0

    return {
        "lines_total": lines_total,
        "lines_parsed": lines_parsed,
        "lines_malformed": lines_malformed,
        "bytes_total": bytes_total,
        "status_classes": status_classes,
        "methods": {k: methods_counter[k] for k in sorted(methods_counter)},
        "top_paths": top_paths,
        "top_ips": top_ips,
        "duration": {
            "count": count,
            "mean": mean_val,
            "p50": p50_val,
            "p95": p95_val,
            "max": max_val,
        },
    }


def _format_table(report: dict) -> str:
    lines = [
        "=== Access Log Report ===",
        f"lines_total: {report['lines_total']}",
        f"lines_parsed: {report['lines_parsed']}",
        f"lines_malformed: {report['lines_malformed']}",
        f"bytes_total: {report['bytes_total']}",
        "",
        "status_classes:",
    ]
    for cls_name, cnt in report["status_classes"].items():
        lines.append(f"  {cls_name}: {cnt}")
    lines.append("")
    lines.append("methods:")
    for method, cnt in report["methods"].items():
        lines.append(f"  {method}: {cnt}")
    lines.append("")
    lines.append("top_paths:")
    for item in report["top_paths"]:
        lines.append(f"  {item['path']}: {item['count']}")
    lines.append("")
    lines.append("top_ips:")
    for item in report["top_ips"]:
        lines.append(f"  {item['ip']}: {item['count']}")
    lines.append("")
    dur = report["duration"]
    lines.append(
        f"duration: count={dur['count']} mean={dur['mean']} "
        f"p50={dur['p50']} p95={dur['p95']} max={dur['max']}"
    )
    return "\n".join(lines) + "\n"


def _positive_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise _argparse.ArgumentTypeError(f"invalid int value: {value!r}") from exc
    if parsed < 1:
        raise _argparse.ArgumentTypeError("--top must be >= 1")
    return parsed


def main(argv: list[str] | None = None) -> int:
    """CLI entry point. Returns the process exit code."""
    parser = _argparse.ArgumentParser(prog="logstats.py", add_help=True)
    parser.add_argument("logfile", help="Path to the access log file")
    parser.add_argument("--top", type=_positive_int, default=5, help="Number of top paths/IPs")
    parser.add_argument(
        "--format",
        choices=("json", "table"),
        default="json",
        dest="fmt",
        help="Output format",
    )
    parser.add_argument("--strict", action="store_true", help="Fail on first malformed line")

    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return int(exc.code) if isinstance(exc.code, int) else 2

    try:
        with open(args.logfile, "r", encoding="utf-8") as fh:
            raw_lines = list(fh)
    except OSError as exc:
        print(f"error reading {args.logfile}: {exc}", file=_sys.stderr)
        return 2

    if args.strict:
        for idx, raw_line in enumerate(raw_lines, start=1):
            if not raw_line.strip():
                continue
            if parse_line(raw_line) is None:
                stripped = raw_line.rstrip("\r\n")
                print(f"malformed line {idx}: {stripped}", file=_sys.stderr)
                return 2

    report = analyze(raw_lines, top=args.top)
    if args.fmt == "json":
        _sys.stdout.write(_json.dumps(report, indent=2) + "\n")
    else:
        _sys.stdout.write(_format_table(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
