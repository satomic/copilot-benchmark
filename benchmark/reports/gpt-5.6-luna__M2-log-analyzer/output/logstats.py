"""Access log parsing and aggregate statistics."""

import argparse as _argparse
import datetime as _datetime
import json as _json
import math as _math
import re as _re
import sys as _sys
from collections import Counter as _Counter
import typing as _typing

_LINE_RE = _re.compile(
    r"(?P<ip>\d{1,3}(?:\.\d{1,3}){3}) - "
    r"(?P<user>-|[A-Za-z0-9_]+) "
    r"\[(?P<timestamp>[^\]]+)\] "
    r'"(?P<method>[A-Z]+) (?P<path>[^"\s]+) (?P<protocol>\S+)" '
    r"(?P<status>\d{3}) (?P<bytes>-|\d+) (?P<duration>\d+(?:\.\d+))"
)
_STATUS_CLASSES = ("2xx", "3xx", "4xx", "5xx", "other")


def parse_line(line: str) -> dict | None:
    """Return a parsed record, or None for a malformed line."""
    if line.endswith("\r\n"):
        line = line[:-2]
    elif line.endswith("\n") or line.endswith("\r"):
        line = line[:-1]
    match = _LINE_RE.fullmatch(line)
    if match is None:
        return None
    fields = match.groupdict()
    octets = [int(part) for part in fields["ip"].split(".")]
    if any(octet > 255 for octet in octets):
        return None
    try:
        timestamp = _datetime.datetime.strptime(
            fields["timestamp"], "%d/%b/%Y:%H:%M:%S %z"
        )
        status = int(fields["status"])
        byte_count = 0 if fields["bytes"] == "-" else int(fields["bytes"])
        duration = float(fields["duration"])
    except (ValueError, OverflowError):
        return None
    return {
        "ip": fields["ip"],
        "user": None if fields["user"] == "-" else fields["user"],
        "timestamp": timestamp,
        "method": fields["method"],
        "path": fields["path"],
        "protocol": fields["protocol"],
        "status": status,
        "bytes": byte_count,
        "duration": duration,
    }


def _percentile(values: list[float], percentile: float) -> float:
    index = max(0, min(len(values) - 1, _math.ceil(percentile / 100 * len(values)) - 1))
    return values[index]


def _top_counts(counts: _Counter[str], limit: int, key_name: str) -> list[dict]:
    entries = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    return [{key_name: name, "count": count} for name, count in entries[: max(0, limit)]]


def analyze(lines: _typing.Iterable[str], top: int = 5) -> dict:
    """Aggregate an iterable of raw access log lines."""
    lines_total = 0
    lines_malformed = 0
    bytes_total = 0
    status_classes = {name: 0 for name in _STATUS_CLASSES}
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
        bytes_total += record["bytes"]
        methods[record["method"]] += 1
        paths[record["path"]] += 1
        ips[record["ip"]] += 1
        durations.append(record["duration"])
        status = record["status"]
        class_name = f"{status // 100}xx" if 200 <= status < 600 else "other"
        status_classes[class_name] += 1

    if durations:
        ordered = sorted(durations)
        duration = {
            "count": len(ordered),
            "mean": round(sum(ordered) / len(ordered), 3),
            "p50": round(_percentile(ordered, 50), 3),
            "p95": round(_percentile(ordered, 95), 3),
            "max": round(max(ordered), 3),
        }
    else:
        duration = {"count": 0, "mean": 0.0, "p50": 0.0, "p95": 0.0, "max": 0.0}
    return {
        "lines_total": lines_total,
        "lines_parsed": lines_total - lines_malformed,
        "lines_malformed": lines_malformed,
        "bytes_total": bytes_total,
        "status_classes": status_classes,
        "methods": dict(sorted(methods.items())),
        "top_paths": _top_counts(paths, top, "path"),
        "top_ips": _top_counts(ips, top, "ip"),
        "duration": duration,
    }


def _table(report: dict) -> str:
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
    """Run the command-line interface and return its process exit code."""
    parser = _argparse.ArgumentParser(prog="logstats.py")
    parser.add_argument("logfile")
    parser.add_argument("--top", type=int, default=5)
    parser.add_argument("--format", choices=("json", "table"), default="json")
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args(argv)
    if args.top < 1:
        parser.error("--top must be at least 1")
    try:
        with open(args.logfile, encoding="utf-8") as logfile:
            if args.strict:
                for line_number, line in enumerate(logfile, 1):
                    if line.strip() and parse_line(line) is None:
                        print(
                            f"malformed line {line_number}: {line.rstrip(chr(13) + chr(10))}",
                            file=_sys.stderr,
                        )
                        return 2
                logfile.seek(0)
            report = analyze(logfile, args.top)
    except (OSError, UnicodeError) as error:
        print(f"cannot read {args.logfile}: {error}", file=_sys.stderr)
        return 2
    if args.format == "json":
        print(_json.dumps(report, indent=2))
    else:
        _sys.stdout.write(_table(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
