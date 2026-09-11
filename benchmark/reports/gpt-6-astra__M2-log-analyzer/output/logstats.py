"""Parse access logs and summarize them as JSON or a readable table."""

import argparse as _argparse
import datetime as _datetime
import json as _json
import math as _math
import re as _re
import statistics as _statistics
import sys as _sys
from collections import Counter as _Counter
from collections.abc import Iterable as _Iterable


_LINE = _re.compile(
    r'(?P<ip>[0-9]{1,3}(?:\.[0-9]{1,3}){3}) - (?P<user>-|\w+) '
    r'\[(?P<day>[0-9]{2})/(?P<month>[A-Z][a-z]{2})/(?P<year>[0-9]{4}):'
    r'(?P<hour>[0-9]{2}):(?P<minute>[0-9]{2}):(?P<second>[0-9]{2}) '
    r'(?P<sign>[+-])(?P<offset_hour>[0-9]{2})(?P<offset_minute>[0-9]{2})\] '
    r'"(?P<method>[A-Z]+) (?P<path>[^\s"]+) (?P<protocol>[^\s"]+)" '
    r'(?P<status>[0-9]{3}) (?P<bytes>-|[0-9]+) '
    r'(?P<duration>[0-9]+(?:\.[0-9]+)?)'
)
_MONTHS = {
    name: number
    for number, name in enumerate(
        ("Jan", "Feb", "Mar", "Apr", "May", "Jun",
         "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"),
        start=1,
    )
}


def _without_terminator(line: str) -> str:
    return line.removesuffix("\n").removesuffix("\r")


def parse_line(line: str) -> dict | None:
    """Return a record dict, or None when the line is malformed."""
    match = _LINE.fullmatch(_without_terminator(line))
    if match is None:
        return None
    fields = match.groupdict()
    if any(int(octet) > 255 for octet in fields["ip"].split(".")):
        return None
    month = _MONTHS.get(fields["month"])
    offset_hour = int(fields["offset_hour"])
    offset_minute = int(fields["offset_minute"])
    if month is None or offset_hour > 23 or offset_minute > 59:
        return None
    offset = _datetime.timedelta(hours=offset_hour, minutes=offset_minute)
    if fields["sign"] == "-":
        offset = -offset
    try:
        timestamp = _datetime.datetime(
            int(fields["year"]), month, int(fields["day"]),
            int(fields["hour"]), int(fields["minute"]), int(fields["second"]),
            tzinfo=_datetime.timezone(offset),
        )
        size = 0 if fields["bytes"] == "-" else int(fields["bytes"])
        # Whole seconds are decimal numbers too; signs and exponents are not.
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
        # The protocol is an opaque token, not restricted to HTTP versions.
        "protocol": fields["protocol"],
        "status": int(fields["status"]),
        "bytes": size,
        "duration": duration,
    }


class _MalformedLine(ValueError):
    pass


def _top_counts(counts: _Counter, key: str, top: int) -> list[dict]:
    return [
        {key: value, "count": count}
        for value, count in sorted(
            counts.items(), key=lambda item: (-item[1], item[0])
        )[:top]
    ]


def _analyze(lines: _Iterable[str], top: int, strict: bool) -> dict:
    if not isinstance(top, int) or isinstance(top, bool) or top < 1:
        raise ValueError("top must be an integer greater than 0")
    total = parsed = malformed = size = 0
    classes = dict.fromkeys(("2xx", "3xx", "4xx", "5xx", "other"), 0)
    methods = _Counter()
    paths = _Counter()
    ips = _Counter()
    durations = []
    for number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        total += 1
        record = parse_line(line)
        if record is None:
            if strict:
                raise _MalformedLine(
                    f"malformed line {number}: {_without_terminator(line)}"
                )
            malformed += 1
            continue
        parsed += 1
        size += record["bytes"]
        status = record["status"]
        classes[f"{status // 100}xx" if 200 <= status < 600 else "other"] += 1
        methods[record["method"]] += 1
        paths[record["path"]] += 1
        ips[record["ip"]] += 1
        durations.append(record["duration"])
    durations.sort()
    duration = {"count": parsed, "mean": 0.0, "p50": 0.0, "p95": 0.0, "max": 0.0}
    if durations:
        duration["mean"] = round(_statistics.mean(durations), 3)
        for name, percentile in (("p50", 50), ("p95", 95)):
            # Integer ceiling avoids floating-point rank errors.
            index = max(0, min(parsed - 1, (percentile * parsed + 99) // 100 - 1))
            duration[name] = round(durations[index], 3)
        duration["max"] = round(durations[-1], 3)
    return {
        "lines_total": total,
        "lines_parsed": parsed,
        "lines_malformed": malformed,
        "bytes_total": size,
        "status_classes": classes,
        "methods": dict(sorted(methods.items())),
        "top_paths": _top_counts(paths, "path", top),
        "top_ips": _top_counts(ips, "ip", top),
        "duration": duration,
    }


def analyze(lines: _Iterable[str], top: int = 5) -> dict:
    """Aggregate raw log lines; top must be a positive integer."""
    return _analyze(lines, top, strict=False)


def _positive_int(value: str) -> int:
    try:
        number = int(value)
    except ValueError:
        raise _argparse.ArgumentTypeError("top must be an integer") from None
    if number < 1:
        raise _argparse.ArgumentTypeError("top must be greater than 0")
    return number


def _table(report: dict) -> str:
    rows = []
    for key, value in report.items():
        if isinstance(value, dict):
            rows.append(f"{key}:")
            rows.extend(f"  {name}: {count}" for name, count in value.items())
        elif isinstance(value, list):
            rows.append(f"{key}:")
            rows.extend(
                "  " + "  ".join(f"{name}: {count}" for name, count in item.items())
                for item in value
            )
        else:
            rows.append(f"{key}: {value}")
    return "\n".join(rows)


def main(argv: list[str] | None = None) -> int:
    """CLI entry point. Returns the process exit code."""
    parser = _argparse.ArgumentParser(description=__doc__)
    parser.add_argument("logfile")
    parser.add_argument("--top", type=_positive_int, default=5)
    parser.add_argument("--format", choices=("json", "table"), default="json")
    parser.add_argument("--strict", action="store_true")
    try:
        args = parser.parse_args(argv)
    except SystemExit as error:
        return error.code
    try:
        with open(args.logfile, encoding="utf-8") as source:
            report = _analyze(source, args.top, args.strict)
    except (_MalformedLine, OSError, UnicodeError) as error:
        print(str(error), file=_sys.stderr)
        return 2
    print(_json.dumps(report, indent=2) if args.format == "json" else _table(report))
    return 0


if __name__ == "__main__":
    _sys.exit(main())
