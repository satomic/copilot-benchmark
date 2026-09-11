"""logstats.py -- Access log analyzer.

Library + CLI for parsing an access log and reporting aggregate statistics.
Importing this module has no side effects; the CLI runs only under
``if __name__ == "__main__":``.
"""

from __future__ import annotations

import argparse
import datetime
import json
import math
import re
import sys
from typing import Iterable

# Regex for a well-formed log line. Anchored on both ends so any deviation
# in shape (extra/missing fields, malformed sub-parts) fails the match.
_LINE_RE = re.compile(
    r"^(?P<ip>\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}) - (?P<user>-|\w+) "
    r"\[(?P<timestamp>\d{2}/[A-Za-z]{3}/\d{4}:\d{2}:\d{2}:\d{2} [+-]\d{4})\] "
    r'"(?P<method>[A-Z]+) (?P<path>\S+) (?P<protocol>[^"]+)" '
    r"(?P<status>\d{3}) (?P<bytes>-|\d+) (?P<duration>\d+(?:\.\d+)?)$"
)

_TIMESTAMP_FMT = "%d/%b/%Y:%H:%M:%S %z"


def parse_line(line: str) -> dict | None:
    """Return a record dict, or None when the line is malformed."""
    # Tolerate a trailing line terminator (\n or \r\n).
    stripped = line.rstrip("\r\n")
    match = _LINE_RE.match(stripped)
    if match is None:
        return None

    try:
        timestamp = datetime.datetime.strptime(
            match.group("timestamp"), _TIMESTAMP_FMT
        )
    except ValueError:
        return None

    user_raw = match.group("user")
    user = None if user_raw == "-" else user_raw

    bytes_raw = match.group("bytes")
    bytes_val = 0 if bytes_raw == "-" else int(bytes_raw)

    return {
        "ip": match.group("ip"),
        "user": user,
        "timestamp": timestamp,
        "method": match.group("method"),
        "path": match.group("path"),
        "protocol": match.group("protocol"),
        "status": int(match.group("status")),
        "bytes": bytes_val,
        "duration": float(match.group("duration")),
    }


def _percentile(sorted_values: list[float], p: float) -> float:
    """Nearest-rank percentile on an ascending sorted list."""
    n = len(sorted_values)
    idx = math.ceil(p / 100 * n) - 1
    idx = max(0, min(idx, n - 1))
    return sorted_values[idx]


def analyze(lines: Iterable[str], top: int = 5) -> dict:
    """Aggregate an iterable of raw log lines into the report structure."""
    lines_total = 0
    lines_parsed = 0
    lines_malformed = 0
    bytes_total = 0
    status_classes = {"2xx": 0, "3xx": 0, "4xx": 0, "5xx": 0, "other": 0}
    methods: dict[str, int] = {}
    path_counts: dict[str, int] = {}
    ip_counts: dict[str, int] = {}
    durations: list[float] = []

    for raw in lines:
        if not raw.strip():
            continue
        lines_total += 1
        rec = parse_line(raw)
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

        methods[rec["method"]] = methods.get(rec["method"], 0) + 1
        path_counts[rec["path"]] = path_counts.get(rec["path"], 0) + 1
        ip_counts[rec["ip"]] = ip_counts.get(rec["ip"], 0) + 1
        durations.append(rec["duration"])

    methods_sorted = dict(sorted(methods.items()))

    top_paths = [
        {"path": p, "count": c}
        for p, c in sorted(path_counts.items(), key=lambda kv: (-kv[1], kv[0]))[:top]
    ]
    top_ips = [
        {"ip": ip, "count": c}
        for ip, c in sorted(ip_counts.items(), key=lambda kv: (-kv[1], kv[0]))[:top]
    ]

    if durations:
        sorted_durations = sorted(durations)
        count = len(sorted_durations)
        mean = sum(sorted_durations) / count
        p50 = _percentile(sorted_durations, 50)
        p95 = _percentile(sorted_durations, 95)
        max_val = sorted_durations[-1]
        duration_stats = {
            "count": count,
            "mean": round(mean, 3),
            "p50": round(p50, 3),
            "p95": round(p95, 3),
            "max": round(max_val, 3),
        }
    else:
        duration_stats = {"count": 0, "mean": 0.0, "p50": 0.0, "p95": 0.0, "max": 0.0}

    return {
        "lines_total": lines_total,
        "lines_parsed": lines_parsed,
        "lines_malformed": lines_malformed,
        "bytes_total": bytes_total,
        "status_classes": status_classes,
        "methods": methods_sorted,
        "top_paths": top_paths,
        "top_ips": top_ips,
        "duration": duration_stats,
    }


def _format_table(report: dict) -> str:
    """Human-readable summary. Not valid JSON."""
    lines = []
    lines.append(f"lines_total: {report['lines_total']}")
    lines.append(f"lines_parsed: {report['lines_parsed']}")
    lines.append(f"lines_malformed: {report['lines_malformed']}")
    lines.append(f"bytes_total: {report['bytes_total']}")
    lines.append("status_classes:")
    for k, v in report["status_classes"].items():
        lines.append(f"  {k} = {v}")
    lines.append("methods:")
    for k, v in report["methods"].items():
        lines.append(f"  {k} = {v}")
    lines.append("top_paths:")
    for entry in report["top_paths"]:
        lines.append(f"  {entry['path']} -> {entry['count']}")
    lines.append("top_ips:")
    for entry in report["top_ips"]:
        lines.append(f"  {entry['ip']} -> {entry['count']}")
    d = report["duration"]
    lines.append(
        "duration: count={} mean={} p50={} p95={} max={}".format(
            d["count"], d["mean"], d["p50"], d["p95"], d["max"]
        )
    )
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    """CLI entry point. Returns the process exit code."""
    parser = argparse.ArgumentParser(
        prog="logstats.py", description="Analyze an access log."
    )
    parser.add_argument("logfile")
    parser.add_argument("--top", type=str, default="5")
    parser.add_argument("--format", choices=["json", "table"], default="json")
    parser.add_argument("--strict", action="store_true")

    try:
        args = parser.parse_args(argv)
    except SystemExit:
        return 2

    # Validate --top manually so non-integer / < 1 values are usage errors
    # rather than argparse's own exit(2) message format (still exit code 2).
    try:
        top = int(args.top)
        if top < 1:
            raise ValueError
    except ValueError:
        print("error: --top must be a positive integer", file=sys.stderr)
        return 2

    try:
        with open(args.logfile, "r", encoding="utf-8") as fh:
            file_lines = fh.readlines()
    except OSError as exc:
        print(f"error: cannot read logfile: {exc}", file=sys.stderr)
        return 2

    if args.strict:
        for i, raw in enumerate(file_lines, start=1):
            if not raw.strip():
                continue
            if parse_line(raw) is None:
                stripped = raw.rstrip("\r\n")
                print(f"malformed line {i}: {stripped}", file=sys.stderr)
                return 2

    report = analyze(file_lines, top=top)

    if args.format == "json":
        print(json.dumps(report, indent=2))
    else:
        print(_format_table(report), end="")

    return 0


if __name__ == "__main__":
    sys.exit(main())
