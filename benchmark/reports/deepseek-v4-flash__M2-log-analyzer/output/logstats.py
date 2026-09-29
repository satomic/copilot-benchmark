"""Access log parser and analyzer.

Parses access logs in the format:
  <ip> - <user> [<timestamp>] "<method> <path> <protocol>" <status> <bytes> <duration>
"""

import argparse
import datetime
import json
import math
import re
import sys
from collections import Counter
from typing import Iterable


_LOG_PATTERN = re.compile(
    r"^(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})"  # ip
    r" - (\S+)"                                   # user
    r' \[(\d{2}/\w{3}/\d{4}:\d{2}:\d{2}:\d{2} [+\-]\d{4})\]'  # timestamp
    r' "([A-Z]+) (\S+) (\S+)"'                    # method, path, protocol
    r" (\d{3})"                                   # status
    r" (\d+|-)"                                   # bytes
    r" (\d+(?:\.\d+)?)$"                          # duration
)

_EMPTY_LINE_RE = re.compile(r"^\s*$")


def parse_line(line: str) -> dict | None:
    """Return a record dict, or None when the line is malformed."""
    stripped = line.rstrip("\r\n")
    if _EMPTY_LINE_RE.match(stripped):
        return None
    m = _LOG_PATTERN.match(stripped)
    if not m:
        return None
    ip, user_str, ts_str, method, path, protocol, status_str, bytes_str, dur_str = (
        m.groups()
    )
    try:
        ts = datetime.datetime.strptime(ts_str, "%d/%b/%Y:%H:%M:%S %z")
    except ValueError:
        return None
    status = int(status_str)
    bytes_val = 0 if bytes_str == "-" else int(bytes_str)
    duration = float(dur_str)
    user = None if user_str == "-" else user_str
    return {
        "ip": ip,
        "user": user,
        "timestamp": ts,
        "method": method,
        "path": path,
        "protocol": protocol,
        "status": status,
        "bytes": bytes_val,
        "duration": duration,
    }


def _classify_status(status: int) -> str:
    if 200 <= status < 300:
        return "2xx"
    if 300 <= status < 400:
        return "3xx"
    if 400 <= status < 500:
        return "4xx"
    if 500 <= status < 600:
        return "5xx"
    return "other"


def _percentile(sorted_vals: list[float], p: float) -> float:
    n = len(sorted_vals)
    if n == 0:
        return 0.0
    idx = math.ceil(p / 100.0 * n) - 1
    idx = max(0, min(idx, n - 1))
    return sorted_vals[idx]


def analyze(lines: Iterable[str], top: int = 5) -> dict:
    """Aggregate an iterable of raw log lines into the report structure."""
    total = 0
    parsed = 0
    malformed = 0
    bytes_total = 0
    status_counts: Counter = Counter()
    method_counts: Counter = Counter()
    path_counts: Counter = Counter()
    ip_counts: Counter = Counter()
    durations: list[float] = []

    for line in lines:
        stripped = line.rstrip("\r\n")
        if _EMPTY_LINE_RE.match(stripped):
            continue
        total += 1
        rec = parse_line(line)
        if rec is None:
            malformed += 1
            continue
        parsed += 1
        bytes_total += rec["bytes"]
        status_counts[_classify_status(rec["status"])] += 1
        method_counts[rec["method"]] += 1
        path_counts[rec["path"]] += 1
        ip_counts[rec["ip"]] += 1
        durations.append(rec["duration"])

    sorted_durations = sorted(durations)

    status_classes = {
        "2xx": status_counts.get("2xx", 0),
        "3xx": status_counts.get("3xx", 0),
        "4xx": status_counts.get("4xx", 0),
        "5xx": status_counts.get("5xx", 0),
        "other": status_counts.get("other", 0),
    }

    methods = dict(sorted(method_counts.items()))

    top_paths = sorted(
        path_counts.items(), key=lambda x: (-x[1], x[0])
    )[:top]
    top_ips = sorted(ip_counts.items(), key=lambda x: (-x[1], x[0]))[:top]

    duration_stats = {
        "count": len(durations),
        "mean": round(sum(durations) / len(durations), 3) if durations else 0.0,
        "p50": round(_percentile(sorted_durations, 50), 3),
        "p95": round(_percentile(sorted_durations, 95), 3),
        "max": round(_percentile(sorted_durations, 100), 3),
    }

    return {
        "lines_total": total,
        "lines_parsed": parsed,
        "lines_malformed": malformed,
        "bytes_total": bytes_total,
        "status_classes": status_classes,
        "methods": methods,
        "top_paths": [{"path": p, "count": c} for p, c in top_paths],
        "top_ips": [{"ip": p, "count": c} for p, c in top_ips],
        "duration": duration_stats,
    }


def _print_table(report: dict) -> None:
    print(f"lines_total: {report['lines_total']}")
    print(f"lines_parsed: {report['lines_parsed']}")
    print(f"lines_malformed: {report['lines_malformed']}")
    print(f"bytes_total: {report['bytes_total']}")
    print(f"status_classes: {report['status_classes']}")
    print(f"methods: {report['methods']}")
    print(f"top_paths: {report['top_paths']}")
    print(f"top_ips: {report['top_ips']}")
    print(f"duration: {report['duration']}")


def main(argv: list[str] | None = None) -> int:
    """CLI entry point. Returns the process exit code."""
    parser = argparse.ArgumentParser(description="Access log analyzer.")
    parser.add_argument("logfile", help="Path to the access log file.")
    parser.add_argument(
        "--top",
        type=int,
        default=5,
        help="Number of top paths and IPs to report.",
    )
    parser.add_argument(
        "--format",
        choices=["json", "table"],
        default="json",
        help="Output format.",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit on the first malformed line.",
    )
    args = parser.parse_args(argv)

    if args.top < 1:
        print("error: --top must be a positive integer", file=sys.stderr)
        return 2

    try:
        with open(args.logfile, "r") as fh:
            if args.strict:
                for lineno, line in enumerate(fh, start=1):
                    stripped = line.rstrip("\r\n")
                    if _EMPTY_LINE_RE.match(stripped):
                        continue
                    rec = parse_line(line)
                    if rec is None:
                        print(
                            f"malformed line {lineno}: {stripped}",
                            file=sys.stderr,
                        )
                        return 2
                    # All lines valid under strict; re-read for analysis
                    fh.seek(0)
                report = analyze(fh, top=args.top)
                if args.format == "table":
                    _print_table(report)
                else:
                    print(json.dumps(report, indent=2))
                return 0
    except (FileNotFoundError, OSError) as e:
        print(f"error: cannot read logfile: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())