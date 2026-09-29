"""Access log analyzer: library and command-line tool."""

import argparse as _argparse
import datetime as _dt
import json as _json
import math as _math
import re as _re
import sys as _sys
from collections import Counter as _Counter
from collections.abc import Iterable as _Iterable

_LINE_RE = _re.compile(
    r"(?P<ip>\d{1,3}(?:\.\d{1,3}){3})"
    r" - "
    r"(?P<user>-|\w+)"
    r" \[(?P<day>\d{2})/(?P<mon>[A-Z][a-z]{2})/(?P<year>\d{4})"
    r":(?P<hh>\d{2}):(?P<mm>\d{2}):(?P<ss>\d{2})"
    r" (?P<tzsign>[+-])(?P<tzh>\d{2})(?P<tzm>\d{2})\]"
    r' "(?P<method>[A-Z]+) (?P<path>\S+) (?P<protocol>\S+)"'
    r" (?P<status>\d{3})"
    r" (?P<bytes>-|\d+)"
    r" (?P<duration>\d+(?:\.\d+)?|\.\d+)"
)

# Month names are mapped manually so parsing does not depend on the C locale.
_MONTHS = {
    name: i
    for i, name in enumerate(
        ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
         "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"],
        start=1,
    )
}


def _parse_timestamp(m: _re.Match) -> _dt.datetime | None:
    month = _MONTHS.get(m["mon"])
    if month is None:
        return None
    tzh, tzm = int(m["tzh"]), int(m["tzm"])
    if tzh > 23 or tzm > 59:
        return None
    offset = _dt.timedelta(hours=tzh, minutes=tzm)
    if m["tzsign"] == "-":
        offset = -offset
    try:
        return _dt.datetime(
            int(m["year"]), month, int(m["day"]),
            int(m["hh"]), int(m["mm"]), int(m["ss"]),
            tzinfo=_dt.timezone(offset),
        )
    except ValueError:
        # Impossible calendar values (e.g. 31/Feb or hour 25) make the line malformed.
        return None


def parse_line(line: str) -> dict | None:
    """Return a record dict, or None when the line is malformed."""
    if not isinstance(line, str):
        return None
    # Only the trailing line terminator is tolerated; any other surrounding
    # whitespace means the line does not match the shape "in full".
    m = _LINE_RE.fullmatch(line.rstrip("\r\n"))
    if m is None:
        return None
    # A dotted quad is only valid IPv4 when every octet is in 0..255.
    if any(int(octet) > 255 for octet in m["ip"].split(".")):
        return None
    ts = _parse_timestamp(m)
    if ts is None:
        return None
    return {
        "ip": m["ip"],
        "user": None if m["user"] == "-" else m["user"],
        "timestamp": ts,
        "method": m["method"],
        "path": m["path"],
        "protocol": m["protocol"],
        "status": int(m["status"]),
        "bytes": 0 if m["bytes"] == "-" else int(m["bytes"]),
        "duration": float(m["duration"]),
    }


def _is_blank(line: str) -> bool:
    return not line.strip()


def _status_class(status: int) -> str:
    if 200 <= status < 600:
        return f"{status // 100}xx"
    return "other"


def _percentile(sorted_values: list[float], p: float) -> float:
    n = len(sorted_values)
    idx = _math.ceil(p / 100 * n) - 1
    idx = max(0, min(n - 1, idx))
    return sorted_values[idx]


def _top(counter: _Counter, key: str, top: int) -> list[dict]:
    items = sorted(counter.items(), key=lambda kv: (-kv[1], kv[0]))
    return [{key: k, "count": c} for k, c in items[:top]]


def _build_report(records: _Iterable[dict], lines_total: int,
                  lines_malformed: int, top: int) -> dict:
    status_classes = {"2xx": 0, "3xx": 0, "4xx": 0, "5xx": 0, "other": 0}
    methods: _Counter = _Counter()
    paths: _Counter = _Counter()
    ips: _Counter = _Counter()
    durations: list[float] = []
    bytes_total = 0
    for rec in records:
        bytes_total += rec["bytes"]
        status_classes[_status_class(rec["status"])] += 1
        methods[rec["method"]] += 1
        paths[rec["path"]] += 1
        ips[rec["ip"]] += 1
        durations.append(rec["duration"])

    durations.sort()
    if durations:
        duration = {
            "count": len(durations),
            "mean": round(sum(durations) / len(durations), 3),
            "p50": round(_percentile(durations, 50), 3),
            "p95": round(_percentile(durations, 95), 3),
            "max": round(durations[-1], 3),
        }
    else:
        duration = {"count": 0, "mean": 0.0, "p50": 0.0, "p95": 0.0, "max": 0.0}

    return {
        "lines_total": lines_total,
        "lines_parsed": len(durations),
        "lines_malformed": lines_malformed,
        "bytes_total": bytes_total,
        "status_classes": status_classes,
        "methods": {k: methods[k] for k in sorted(methods)},
        "top_paths": _top(paths, "path", top),
        "top_ips": _top(ips, "ip", top),
        "duration": duration,
    }


def analyze(lines: _Iterable[str], top: int = 5) -> dict:
    """Aggregate an iterable of raw log lines into the report structure."""
    records: list[dict] = []
    total = malformed = 0
    for line in lines:
        if _is_blank(line):
            continue
        total += 1
        rec = parse_line(line)
        if rec is None:
            malformed += 1
        else:
            records.append(rec)
    return _build_report(records, total, malformed, top)


def _format_table(report: dict) -> str:
    out = []
    for key in ("lines_total", "lines_parsed", "lines_malformed", "bytes_total"):
        out.append(f"{key:<16} {report[key]}")
    out.append("")
    out.append("status_classes")
    for k, v in report["status_classes"].items():
        out.append(f"  {k:<14} {v}")
    out.append("")
    out.append("methods")
    for k, v in report["methods"].items():
        out.append(f"  {k:<14} {v}")
    out.append("")
    out.append("top_paths")
    for e in report["top_paths"]:
        out.append(f"  {e['count']:>6}  {e['path']}")
    out.append("")
    out.append("top_ips")
    for e in report["top_ips"]:
        out.append(f"  {e['count']:>6}  {e['ip']}")
    out.append("")
    out.append("duration")
    for k, v in report["duration"].items():
        out.append(f"  {k:<14} {v}")
    return "\n".join(out) + "\n"


def _positive_int(value: str) -> int:
    try:
        n = int(value)
    except ValueError:
        raise _argparse.ArgumentTypeError(f"invalid integer: {value!r}")
    if n < 1:
        raise _argparse.ArgumentTypeError(f"must be >= 1: {value!r}")
    return n


def _build_parser() -> _argparse.ArgumentParser:
    parser = _argparse.ArgumentParser(
        prog="logstats.py", description="Report aggregate statistics for an access log."
    )
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
    except SystemExit as exc:
        # argparse exits 0 for --help and 2 for usage errors; return rather than exit.
        return exc.code if isinstance(exc.code, int) else 2

    try:
        with open(args.logfile, encoding="utf-8", errors="replace") as fh:
            lines = fh.readlines()
    except OSError as exc:
        print(f"logstats: cannot read {args.logfile}: {exc}", file=_sys.stderr)
        return 2

    records: list[dict] = []
    total = malformed = 0
    # Line numbers count every physical line in the file, blank ones included.
    for lineno, line in enumerate(lines, start=1):
        if _is_blank(line):
            continue
        total += 1
        rec = parse_line(line)
        if rec is None:
            if args.strict:
                print(f"malformed line {lineno}: {line.rstrip(chr(13) + chr(10))}",
                      file=_sys.stderr)
                return 2
            malformed += 1
        else:
            records.append(rec)

    report = _build_report(records, total, malformed, args.top)
    if args.format == "json":
        _sys.stdout.write(_json.dumps(report, indent=2) + "\n")
    else:
        _sys.stdout.write(_format_table(report))
    return 0


if __name__ == "__main__":
    _sys.exit(main())
