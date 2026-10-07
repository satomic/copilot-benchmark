"""Parse access logs and report aggregate statistics using only the standard library."""

import argparse as _argparse
import collections as _collections
import datetime as _datetime
import json as _json
import math as _math
import re as _re
import sys as _sys
from collections.abc import Iterable as _Iterable


_LINE = _re.compile(
    r'(?P<ip>[0-9]{1,3}(?:\.[0-9]{1,3}){3}) - (?P<user>-|\w+) '
    r'\[(?P<day>[0-9]{2})/(?P<month>[A-Z][a-z]{2})/(?P<year>[0-9]{4}):'
    r'(?P<hour>[0-9]{2}):(?P<minute>[0-9]{2}):(?P<second>[0-9]{2}) '
    r'(?P<sign>[+-])(?P<offset_hour>[0-9]{2})(?P<offset_minute>[0-9]{2})\] '
    r'"(?P<method>[A-Z]+) (?P<path>[^\s"]+) (?P<protocol>HTTP/[0-9]+\.[0-9]+)" '
    r'(?P<status>[0-9]{3}) (?P<bytes>[0-9]+|-) '
    r'(?P<duration>[0-9]+(?:\.[0-9]+)?)'
)
_MONTHS = {
    name: number
    for number, name in enumerate(
        ("Jan", "Feb", "Mar", "Apr", "May", "Jun",
         "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"), 1
    )
}


def _without_terminator(line: str) -> str:
    if line.endswith("\r\n"):
        return line[:-2]
    if line.endswith(("\n", "\r")):
        return line[:-1]
    return line


def parse_line(line: str) -> dict | None:
    """Return a record dict, or None when the line is malformed."""
    # Treat protocol as HTTP/version and duration as non-negative fixed-point seconds.
    match = _LINE.fullmatch(_without_terminator(line))
    if match is None:
        return None
    fields = match.groupdict()
    if any(int(octet) > 255 for octet in fields["ip"].split(".")):
        return None
    month = _MONTHS.get(fields["month"])
    if month is None:
        return None
    try:
        offset_hour = int(fields["offset_hour"])
        offset_minute = int(fields["offset_minute"])
        if offset_hour > 23 or offset_minute > 59:
            return None
        offset = _datetime.timedelta(hours=offset_hour, minutes=offset_minute)
        if fields["sign"] == "-":
            offset = -offset
        timestamp = _datetime.datetime(
            int(fields["year"]), month, int(fields["day"]),
            int(fields["hour"]), int(fields["minute"]), int(fields["second"]),
            tzinfo=_datetime.timezone(offset),
        )
        byte_count = 0 if fields["bytes"] == "-" else int(fields["bytes"])
        duration = float(fields["duration"])
    except ValueError:
        return None
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
        "bytes": byte_count,
        "duration": duration,
    }


class _MalformedLine(ValueError):
    pass


def _top_entries(counts: _collections.Counter, key: str, top: int) -> list[dict]:
    return [
        {key: value, "count": count}
        for value, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:top]
    ]


def _analyze(lines: _Iterable[str], top: int, strict: bool) -> dict:
    if not isinstance(top, int) or top < 1:
        raise ValueError("top must be a positive integer")
    total = parsed = malformed = byte_count = 0
    status_classes = dict.fromkeys(("2xx", "3xx", "4xx", "5xx", "other"), 0)
    methods = _collections.Counter()
    paths = _collections.Counter()
    ips = _collections.Counter()
    durations = []
    for number, line in enumerate(lines, 1):
        if not line.strip():
            continue
        total += 1
        record = parse_line(line)
        if record is None:
            if strict:
                raise _MalformedLine(f"malformed line {number}: {_without_terminator(line)}")
            malformed += 1
            continue
        parsed += 1
        byte_count += record["bytes"]
        status = record["status"]
        status_classes[f"{status // 100}xx" if 200 <= status < 600 else "other"] += 1
        methods[record["method"]] += 1
        paths[record["path"]] += 1
        ips[record["ip"]] += 1
        durations.append(record["duration"])
    durations.sort()
    duration = {"count": parsed, "mean": 0.0, "p50": 0.0, "p95": 0.0, "max": 0.0}
    if durations:
        duration.update({
            # Divide before summing so a finite mean cannot overflow its intermediate sum.
            "mean": round(_math.fsum(value / parsed for value in durations), 3),
            "p50": round(durations[(_math.ceil(parsed * 50 / 100) - 1)], 3),
            "p95": round(durations[(_math.ceil(parsed * 95 / 100) - 1)], 3),
            "max": round(durations[-1], 3),
        })
    return {
        "lines_total": total,
        "lines_parsed": parsed,
        "lines_malformed": malformed,
        "bytes_total": byte_count,
        "status_classes": status_classes,
        "methods": dict(sorted(methods.items())),
        "top_paths": _top_entries(paths, "path", top),
        "top_ips": _top_entries(ips, "ip", top),
        "duration": duration,
    }


def analyze(lines: _Iterable[str], top: int = 5) -> dict:
    """Aggregate an iterable of raw log lines into the report structure."""
    return _analyze(lines, top, strict=False)


def _positive_integer(value: str) -> int:
    try:
        number = int(value)
    except ValueError:
        raise _argparse.ArgumentTypeError("top must be a positive integer") from None
    if number < 1:
        raise _argparse.ArgumentTypeError("top must be a positive integer")
    return number


def main(argv: list[str] | None = None) -> int:
    """CLI entry point. Returns the process exit code."""
    parser = _argparse.ArgumentParser(description=__doc__)
    parser.add_argument("logfile")
    parser.add_argument("--top", type=_positive_integer, default=5)
    parser.add_argument("--format", choices=("json", "table"), default="json")
    parser.add_argument("--strict", action="store_true")
    try:
        args = parser.parse_args(argv)
    except SystemExit as error:
        return int(error.code)
    try:
        with open(args.logfile, encoding="utf-8") as source:
            report = _analyze(source, args.top, args.strict)
    except (_MalformedLine, OSError, UnicodeError) as error:
        print(error, file=_sys.stderr)
        return 2
    if args.format == "json":
        print(_json.dumps(report, indent=2))
    else:
        for key, value in report.items():
            print(f"{key}: {value}")
    return 0


if __name__ == "__main__":
    _sys.exit(main())
