import argparse
import json
import re
import sys
from collections import Counter
from datetime import datetime
from math import ceil
from typing import Iterable


_STATUS_CLASSES = ("2xx", "3xx", "4xx", "5xx", "other")


def _is_valid_ipv4(ip: str) -> bool:
    if not isinstance(ip, str):
        return False
    parts = ip.split(".")
    if len(parts) != 4:
        return False
    for part in parts:
        if not part or not part.isdigit():
            return False
        value = int(part)
        if value < 0 or value > 255:
            return False
    return True


def parse_line(line: str) -> dict | None:
    """Return a record dict, or None when the line is malformed."""
    if line is None:
        return None
    text = line.rstrip("\r\n")
    if not text or not text.strip():
        return None

    pattern = re.compile(
        r'^(?P<ip>(?:\d{1,3}\.){3}\d{1,3}) - (?P<user>-|[\w]+) '
        r'\[(?P<timestamp>\d{2}/[A-Za-z]{3}/\d{4}:\d{2}:\d{2}:\d{2} [+-]\d{4})\] '
        r'"(?P<method>[A-Z]+) (?P<path>\S+) (?P<protocol>[^"\s]+)" '
        r'(?P<status>\d{3}) (?P<bytes>-|\d+) (?P<duration>\d+(?:\.\d+)?)$'
    )
    match = pattern.fullmatch(text)
    if match is None:
        return None

    ip = match.group("ip")
    if not _is_valid_ipv4(ip):
        return None

    user = match.group("user")
    if user == "-":
        user = None

    try:
        timestamp = datetime.strptime(match.group("timestamp"), "%d/%b/%Y:%H:%M:%S %z")
    except ValueError:
        return None

    body = match.group("bytes")
    bytes_value = 0 if body == "-" else int(body)
    status = int(match.group("status"))
    duration = float(match.group("duration"))

    return {
        "ip": ip,
        "user": user,
        "timestamp": timestamp,
        "method": match.group("method"),
        "path": match.group("path"),
        "protocol": match.group("protocol"),
        "status": status,
        "bytes": bytes_value,
        "duration": duration,
    }


def _nearest_rank(values: list[float], percentile: int) -> float:
    if not values:
        return 0.0
    n = len(values)
    index = ceil((percentile / 100) * n) - 1
    index = max(0, min(index, n - 1))
    return values[index]


def _build_report(records: list[dict], top: int) -> dict:
    status_counts = {key: 0 for key in _STATUS_CLASSES}
    method_counts: Counter[str] = Counter()
    path_counts: Counter[str] = Counter()
    ip_counts: Counter[str] = Counter()
    durations: list[float] = []
    bytes_total = 0

    for record in records:
        bytes_total += record["bytes"]
        status = record["status"]
        if 200 <= status < 300:
            status_counts["2xx"] += 1
        elif 300 <= status < 400:
            status_counts["3xx"] += 1
        elif 400 <= status < 500:
            status_counts["4xx"] += 1
        elif 500 <= status < 600:
            status_counts["5xx"] += 1
        else:
            status_counts["other"] += 1

        method_counts[record["method"]] += 1
        path_counts[record["path"]] += 1
        ip_counts[record["ip"]] += 1
        durations.append(record["duration"])

    methods = {key: method_counts[key] for key in sorted(method_counts)}

    top_paths = [
        {"path": path, "count": count}
        for path, count in sorted(path_counts.items(), key=lambda item: (-item[1], item[0]))[:top]
    ]
    top_ips = [
        {"ip": ip, "count": count}
        for ip, count in sorted(ip_counts.items(), key=lambda item: (-item[1], item[0]))[:top]
    ]

    if durations:
        mean = sum(durations) / len(durations)
        p50 = _nearest_rank(sorted(durations), 50)
        p95 = _nearest_rank(sorted(durations), 95)
        maximum = max(durations)
    else:
        mean = p50 = p95 = maximum = 0.0

    duration_report = {
        "count": len(durations),
        "mean": round(mean, 3),
        "p50": round(p50, 3),
        "p95": round(p95, 3),
        "max": round(maximum, 3),
    }

    return {
        "lines_total": 0,
        "lines_parsed": len(records),
        "lines_malformed": 0,
        "bytes_total": bytes_total,
        "status_classes": status_counts,
        "methods": methods,
        "top_paths": top_paths,
        "top_ips": top_ips,
        "duration": duration_report,
    }


def analyze(lines: Iterable[str], top: int = 5) -> dict:
    """Aggregate an iterable of raw log lines into the report structure."""
    if top < 1:
        raise ValueError("top must be at least 1")

    lines_total = 0
    lines_parsed = 0
    lines_malformed = 0
    records: list[dict] = []

    for raw_line in lines:
        if raw_line is None:
            continue
        if not raw_line.strip():
            continue
        lines_total += 1
        record = parse_line(raw_line)
        if record is None:
            lines_malformed += 1
            continue
        records.append(record)
        lines_parsed += 1

    report = _build_report(records, top)
    report["lines_total"] = lines_total
    report["lines_malformed"] = lines_malformed
    return report


def _render_table(report: dict) -> str:
    lines = [
        f"lines_total: {report['lines_total']}",
        f"lines_parsed: {report['lines_parsed']}",
        f"lines_malformed: {report['lines_malformed']}",
        f"bytes_total: {report['bytes_total']}",
        f"status_classes: {report['status_classes']}",
        f"methods: {report['methods']}",
        f"top_paths: {report['top_paths']}",
        f"top_ips: {report['top_ips']}",
        f"duration: {report['duration']}",
    ]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    """CLI entry point. Returns the process exit code."""
    parser = argparse.ArgumentParser(description="Analyze access log files.")
    parser.add_argument("logfile")
    parser.add_argument("--top", default="5")
    parser.add_argument("--format", choices=("json", "table"), default="json")
    parser.add_argument("--strict", action="store_true")

    argv = sys.argv[1:] if argv is None else argv
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return int(exc.code) if isinstance(exc.code, int) else 2

    try:
        top = int(args.top)
    except ValueError:
        print("error: --top must be an integer >= 1", file=sys.stderr)
        return 2
    if top < 1:
        print("error: --top must be an integer >= 1", file=sys.stderr)
        return 2

    try:
        with open(args.logfile, "r", encoding="utf-8", errors="replace") as handle:
            if args.strict:
                records: list[dict] = []
                lines_total = 0
                for line_no, raw_line in enumerate(handle, start=1):
                    if not raw_line.strip():
                        continue
                    lines_total += 1
                    record = parse_line(raw_line)
                    if record is None:
                        print(f"malformed line {line_no}: {raw_line.rstrip(chr(10)).rstrip(chr(13))}", file=sys.stderr)
                        return 2
                    records.append(record)
                report = _build_report(records, top)
                report["lines_total"] = lines_total
                report["lines_malformed"] = 0
            else:
                report = analyze(handle, top=top)
    except OSError as exc:
        print(f"error: unable to read '{args.logfile}': {exc}", file=sys.stderr)
        return 2

    if args.format == "json":
        sys.stdout.write(json.dumps(report, indent=2) + "\n")
    else:
        sys.stdout.write(_render_table(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
