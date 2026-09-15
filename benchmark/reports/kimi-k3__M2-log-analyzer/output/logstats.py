"""Access log analyzer: parse log lines and report aggregate statistics."""

import argparse as _argparse
import datetime as _datetime
import json as _json
import math as _math
import re as _re
import sys as _sys
from collections import Counter as _Counter
from typing import Iterable as _Iterable

# <ip> - <user> [<timestamp>] "<method> <path> <protocol>" <status> <bytes> <duration>
_LINE_RE = _re.compile(
    r"^"
    r"(?P<ip>\d{1,3}(?:\.\d{1,3}){3})"
    r" - (?P<user>-|\w+)"
    r" \[(?P<timestamp>\d{2}/[A-Za-z]{3}/\d{4}:\d{2}:\d{2}:\d{2} [+-]\d{4})\]"
    r' "(?P<method>[A-Z]+) (?P<path>\S+) (?P<protocol>\S+)"'
    r" (?P<status>\d{3})"
    r" (?P<bytes>-|\d+)"
    r" (?P<duration>\d+(?:\.\d+)?)"
    r"$"
)

_TS_FORMAT = "%d/%b/%Y:%H:%M:%S %z"


def parse_line(line: str) -> dict | None:
    """Return a record dict, or None when the line is malformed."""
    # Tolerate a trailing line terminator ("\n" or "\r\n") from file iteration.
    line = line.rstrip("\r\n")
    match = _LINE_RE.match(line)
    if match is None:
        return None
    groups = match.groupdict()
    try:
        timestamp = _datetime.datetime.strptime(groups["timestamp"], _TS_FORMAT)
    except ValueError:
        return None
    return {
        "ip": groups["ip"],
        "user": None if groups["user"] == "-" else groups["user"],
        "timestamp": timestamp,
        "method": groups["method"],
        "path": groups["path"],
        "protocol": groups["protocol"],
        "status": int(groups["status"]),
        "bytes": 0 if groups["bytes"] == "-" else int(groups["bytes"]),
        "duration": float(groups["duration"]),
    }


def _percentile(sorted_values: list[float], p: int) -> float:
    """Nearest-rank percentile on an ascending sorted list."""
    n = len(sorted_values)
    index = _math.ceil(p / 100 * n) - 1
    index = max(0, min(index, n - 1))
    return sorted_values[index]


def analyze(lines: _Iterable[str], top: int = 5) -> dict:
    """Aggregate an _Iterable of raw log lines into the report structure."""
    lines_total = 0
    lines_parsed = 0
    lines_malformed = 0
    bytes_total = 0
    status_classes = {"2xx": 0, "3xx": 0, "4xx": 0, "5xx": 0, "other": 0}
    methods: _Counter = _Counter()
    paths: _Counter = _Counter()
    ips: _Counter = _Counter()
    durations: list[float] = []

    for line in lines:
        # Blank lines (empty or whitespace-only) are ignored entirely.
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
        methods[record["method"]] += 1
        paths[record["path"]] += 1
        ips[record["ip"]] += 1
        durations.append(record["duration"])

    def _top(_Counter: _Counter, key: str) -> list[dict]:
        ranked = sorted(_Counter.items(), key=lambda item: (-item[1], item[0]))[:top]
        return [{key: name, "count": count} for name, count in ranked]

    if durations:
        sorted_durations = sorted(durations)
        duration_stats = {
            "count": len(durations),
            "mean": round(sum(durations) / len(durations), 3),
            "p50": round(_percentile(sorted_durations, 50), 3),
            "p95": round(_percentile(sorted_durations, 95), 3),
            "max": round(max(durations), 3),
        }
    else:
        duration_stats = {"count": 0, "mean": 0.0, "p50": 0.0, "p95": 0.0, "max": 0.0}

    return {
        "lines_total": lines_total,
        "lines_parsed": lines_parsed,
        "lines_malformed": lines_malformed,
        "bytes_total": bytes_total,
        "status_classes": status_classes,
        "methods": {name: methods[name] for name in sorted(methods)},
        "top_paths": _top(paths, "path"),
        "top_ips": _top(ips, "ip"),
        "duration": duration_stats,
    }


def _format_table(report: dict) -> str:
    """Render a human-readable, non-JSON summary of the report."""
    lines = [
        "Access log summary",
        f"  lines_total     : {report['lines_total']}",
        f"  lines_parsed    : {report['lines_parsed']}",
        f"  lines_malformed : {report['lines_malformed']}",
        f"  bytes_total     : {report['bytes_total']}",
        "  status_classes:",
    ]
    for name, count in report["status_classes"].items():
        lines.append(f"    {name}: {count}")
    lines.append("  methods:")
    for name, count in report["methods"].items():
        lines.append(f"    {name}: {count}")
    lines.append("  top_paths:")
    for entry in report["top_paths"]:
        lines.append(f"    {entry['path']} ({entry['count']})")
    lines.append("  top_ips:")
    for entry in report["top_ips"]:
        lines.append(f"    {entry['ip']} ({entry['count']})")
    duration = report["duration"]
    lines.append("  duration:")
    lines.append(
        f"    count={duration['count']} mean={duration['mean']}"
        f" p50={duration['p50']} p95={duration['p95']} max={duration['max']}"
    )
    return "\n".join(lines) + "\n"


def _positive_int(value: str) -> int:
    try:
        number = int(value)
    except ValueError:
        raise _argparse.ArgumentTypeError(f"invalid integer: {value!r}") from None
    if number < 1:
        raise _argparse.ArgumentTypeError("--top must be at least 1")
    return number


def main(argv: list[str] | None = None) -> int:
    """CLI entry point. Returns the process exit code."""
    parser = _argparse.ArgumentParser(
        prog="logstats.py", description="Analyze an access log file."
    )
    parser.add_argument("logfile", help="path to the access log file")
    parser.add_argument("--top", type=_positive_int, default=5,
                        help="number of top paths/IPs to report (default 5)")
    parser.add_argument("--format", choices=("json", "table"), default="json",
                        help="output format (default json)")
    parser.add_argument("--strict", action="store_true",
                        help="abort on the first malformed line")
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:  # argparse usage error: stderr already written
        return exc.code if isinstance(exc.code, int) else 2

    try:
        with open(args.logfile, "r", encoding="utf-8") as fh:
            raw_lines = fh.readlines()
    except OSError as exc:
        print(f"error: cannot read {args.logfile}: {exc}", file=_sys.stderr)
        return 2

    if args.strict:
        checked = []
        for number, line in enumerate(raw_lines, start=1):
            if not line.strip():
                continue
            if parse_line(line) is None:
                print(
                    f"malformed line {number}: {line.rstrip(chr(10)).rstrip(chr(13))}",
                    file=_sys.stderr,
                )
                return 2
            checked.append(line)
        raw_lines = checked

    report = analyze(raw_lines, top=args.top)
    if args.format == "json":
        _sys.stdout.write(_json.dumps(report, indent=2) + "\n")
    else:
        _sys.stdout.write(_format_table(report))
    return 0


if __name__ == "__main__":
    _sys.exit(main())
