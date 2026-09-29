"""Parse access logs and report aggregate statistics."""

import argparse as _argparse
import datetime as _datetime
import json as _json
import math as _math
import re as _re
import sys as _sys
from collections import Counter as _Counter
from collections.abc import Iterable as _Iterable


_LINE_RE = _re.compile(
    r"(?P<ip>[0-9]{1,3}(?:\.[0-9]{1,3}){3}) - "
    r"(?P<user>-|\w+) "
    r"\[(?P<timestamp>[0-9]{2}/[A-Z][a-z]{2}/[0-9]{4}:"
    r"[0-9]{2}:[0-9]{2}:[0-9]{2} [+-][0-9]{4})\] "
    r'"(?P<method>[A-Z]+) (?P<path>\S+) (?P<protocol>\S+)" '
    r"(?P<status>[0-9]{3}) (?P<bytes>-|[0-9]+) "
    r"(?P<duration>[0-9]+(?:\.[0-9]+)?)",
    _re.ASCII,
)


class _ArgumentError(Exception):
    pass


class _ArgumentParser(_argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise _ArgumentError(message)


def _valid_ip(address: str) -> bool:
    parts = address.split(".")
    return all(int(part) <= 255 and (part == "0" or not part.startswith("0")) for part in parts)


def parse_line(line: str) -> dict | None:
    """Return a record dict, or None when the line is malformed."""
    if line.endswith("\n"):
        line = line[:-1]
        if line.endswith("\r"):
            line = line[:-1]

    match = _LINE_RE.fullmatch(line)
    if match is None or not _valid_ip(match["ip"]):
        return None

    try:
        timestamp = _datetime.datetime.strptime(
            match["timestamp"], "%d/%b/%Y:%H:%M:%S %z"
        )
    except ValueError:
        return None

    return {
        "ip": match["ip"],
        "user": None if match["user"] == "-" else match["user"],
        "timestamp": timestamp,
        "method": match["method"],
        "path": match["path"],
        "protocol": match["protocol"],
        "status": int(match["status"]),
        "bytes": 0 if match["bytes"] == "-" else int(match["bytes"]),
        "duration": float(match["duration"]),
    }


def _nearest_rank(values: list[float], percentile: int) -> float:
    index = _math.ceil(percentile / 100 * len(values)) - 1
    return values[max(0, min(index, len(values) - 1))]


def _top_items(counter: _Counter, key_name: str, top: int) -> list[dict]:
    ordered = sorted(counter.items(), key=lambda item: (-item[1], item[0]))
    return [{key_name: key, "count": count} for key, count in ordered[:top]]


def analyze(lines: _Iterable[str], top: int = 5) -> dict:
    """Aggregate an iterable of raw log lines into the report structure."""
    if top < 1:
        raise ValueError("top must be at least 1")

    lines_total = 0
    lines_parsed = 0
    bytes_total = 0
    status_classes = {"2xx": 0, "3xx": 0, "4xx": 0, "5xx": 0, "other": 0}
    methods = _Counter()
    paths = _Counter()
    ips = _Counter()
    durations = []

    for line in lines:
        if not line.strip():
            continue
        lines_total += 1
        record = parse_line(line)
        if record is None:
            continue

        lines_parsed += 1
        bytes_total += record["bytes"]
        status = record["status"]
        if 200 <= status < 600:
            status_classes[f"{status // 100}xx"] += 1
        else:
            status_classes["other"] += 1
        methods[record["method"]] += 1
        paths[record["path"]] += 1
        ips[record["ip"]] += 1
        durations.append(record["duration"])

    durations.sort()
    if durations:
        duration = {
            "count": len(durations),
            "mean": round(sum(durations) / len(durations), 3),
            "p50": round(_nearest_rank(durations, 50), 3),
            "p95": round(_nearest_rank(durations, 95), 3),
            "max": round(durations[-1], 3),
        }
    else:
        duration = {"count": 0, "mean": 0.0, "p50": 0.0, "p95": 0.0, "max": 0.0}

    return {
        "lines_total": lines_total,
        "lines_parsed": lines_parsed,
        "lines_malformed": lines_total - lines_parsed,
        "bytes_total": bytes_total,
        "status_classes": status_classes,
        "methods": dict(sorted(methods.items())),
        "top_paths": _top_items(paths, "path", top),
        "top_ips": _top_items(ips, "ip", top),
        "duration": duration,
    }


def _format_table(report: dict) -> str:
    lines = [
        f"lines_total: {report['lines_total']}",
        f"lines_parsed: {report['lines_parsed']}",
        f"lines_malformed: {report['lines_malformed']}",
        f"bytes_total: {report['bytes_total']}",
        f"status_classes: {report['status_classes']}",
        f"methods: {report['methods']}",
        "top_paths:",
    ]
    lines.extend(
        f"  {item['path']}: {item['count']}" for item in report["top_paths"]
    )
    lines.append("top_ips:")
    lines.extend(f"  {item['ip']}: {item['count']}" for item in report["top_ips"])
    lines.append(f"duration: {report['duration']}")
    return "\n".join(lines)


def _positive_int(value: str) -> int:
    try:
        number = int(value)
    except ValueError as error:
        raise _argparse.ArgumentTypeError("must be an integer") from error
    if number < 1:
        raise _argparse.ArgumentTypeError("must be at least 1")
    return number


def _build_parser() -> _ArgumentParser:
    parser = _ArgumentParser(prog="logstats.py")
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
    except _ArgumentError as error:
        print(f"{parser.prog}: error: {error}", file=_sys.stderr)
        return 2

    try:
        with open(args.logfile, encoding="utf-8") as file:
            lines = list(file)
    except (OSError, UnicodeError) as error:
        print(f"{parser.prog}: {error}", file=_sys.stderr)
        return 2

    if args.strict:
        for number, line in enumerate(lines, 1):
            if line.strip() and parse_line(line) is None:
                text = line.removesuffix("\n").removesuffix("\r")
                print(f"malformed line {number}: {text}", file=_sys.stderr)
                return 2

    report = analyze(lines, args.top)
    if args.format == "json":
        print(_json.dumps(report, indent=2))
    else:
        print(_format_table(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
