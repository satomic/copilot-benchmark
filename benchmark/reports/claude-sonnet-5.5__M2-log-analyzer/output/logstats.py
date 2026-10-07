"""Access log analyzer: library + CLI."""
import argparse as _argparse
import json as _json
import math as _math
import re as _re
import sys as _sys
from collections import Counter as _Counter
from datetime import datetime as _datetime, timedelta as _timedelta, timezone as _timezone
from typing import Iterable as _Iterable

_LINE_RE = _re.compile(
    r"(?P<ip>[0-9]{1,3}(?:\.[0-9]{1,3}){3}) - (?P<user>\w+|-) "
    r"\[(?P<day>[0-9]{2})/(?P<mon>[A-Za-z]{3})/(?P<year>[0-9]{4}):"
    r"(?P<hh>[0-9]{2}):(?P<mm>[0-9]{2}):(?P<ss>[0-9]{2}) "
    r"(?P<sign>[+-])(?P<tzh>[0-9]{2})(?P<tzm>[0-9]{2})\] "
    r'"(?P<method>[A-Z]+) (?P<path>\S+) (?P<protocol>\S+)" '
    r"(?P<status>[0-9]{3}) (?P<bytes>[0-9]+|-) "
    r"(?P<duration>[0-9]+(?:\.[0-9]+)?)"
)

_MONTHS = {m: i for i, m in enumerate(
    ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"], 1)}


def parse_line(line: str) -> dict | None:
    """Return a record dict, or None when the line is malformed."""
    # Only a trailing \n / \r\n (or lone \r) terminator is stripped.
    line = line.rstrip("\r\n")
    m = _LINE_RE.fullmatch(line)
    if not m:
        return None
    octets = m["ip"].split(".")
    if any(int(o) > 255 for o in octets):
        return None
    mon = _MONTHS.get(m["mon"])
    if mon is None:
        return None
    tzh, tzm = int(m["tzh"]), int(m["tzm"])
    if tzm > 59:
        return None
    offset = _timedelta(hours=tzh, minutes=tzm)
    if m["sign"] == "-":
        offset = -offset
    try:
        ts = _datetime(int(m["year"]), mon, int(m["day"]), int(m["hh"]),
                      int(m["mm"]), int(m["ss"]), tzinfo=_timezone(offset))
    except ValueError:
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


def _percentile(sorted_vals: list, p: float) -> float:
    n = len(sorted_vals)
    idx = min(max(_math.ceil(p / 100 * n) - 1, 0), n - 1)
    return sorted_vals[idx]


def _top(counter: _Counter, key: str, top: int) -> list:
    items = sorted(counter.items(), key=lambda kv: (-kv[1], kv[0]))[:max(top, 0)]
    return [{key: k, "count": c} for k, c in items]


def analyze(lines: _Iterable[str], top: int = 5) -> dict:
    """Aggregate an iterable of raw log lines into the report structure."""
    total = parsed = malformed = bytes_total = 0
    classes = {"2xx": 0, "3xx": 0, "4xx": 0, "5xx": 0, "other": 0}
    methods: _Counter = _Counter()
    paths: _Counter = _Counter()
    ips: _Counter = _Counter()
    durations: list = []
    for line in lines:
        if not line.strip():
            continue
        total += 1
        rec = parse_line(line)
        if rec is None:
            malformed += 1
            continue
        parsed += 1
        bytes_total += rec["bytes"]
        s = rec["status"]
        classes[f"{s // 100}xx" if 200 <= s < 600 and s // 100 != 1 else "other"] += 1
        methods[rec["method"]] += 1
        paths[rec["path"]] += 1
        ips[rec["ip"]] += 1
        durations.append(rec["duration"])
    durations.sort()
    if durations:
        dur = {
            "count": len(durations),
            "mean": round(sum(durations) / len(durations), 3),
            "p50": round(_percentile(durations, 50), 3),
            "p95": round(_percentile(durations, 95), 3),
            "max": round(durations[-1], 3),
        }
    else:
        dur = {"count": 0, "mean": 0.0, "p50": 0.0, "p95": 0.0, "max": 0.0}
    return {
        "lines_total": total,
        "lines_parsed": parsed,
        "lines_malformed": malformed,
        "bytes_total": bytes_total,
        "status_classes": classes,
        "methods": dict(sorted(methods.items())),
        "top_paths": _top(paths, "path", top),
        "top_ips": _top(ips, "ip", top),
        "duration": dur,
    }


def _format_table(report: dict) -> str:
    out = []
    for k in ("lines_total", "lines_parsed", "lines_malformed", "bytes_total"):
        out.append(f"{k}: {report[k]}")
    out.append("status_classes:")
    out += [f"  {k}: {v}" for k, v in report["status_classes"].items()]
    out.append("methods:")
    out += [f"  {k}: {v}" for k, v in report["methods"].items()]
    out.append("top_paths:")
    out += [f"  {e['count']:>6}  {e['path']}" for e in report["top_paths"]]
    out.append("top_ips:")
    out += [f"  {e['count']:>6}  {e['ip']}" for e in report["top_ips"]]
    out.append("duration:")
    out += [f"  {k}: {v}" for k, v in report["duration"].items()]
    return "\n".join(out) + "\n"


class _Parser(_argparse.ArgumentParser):
    def error(self, message):
        self.print_usage(_sys.stderr)
        _sys.stderr.write(f"{self.prog}: error: {message}\n")
        raise SystemExit(2)


def _positive_int(text: str) -> int:
    try:
        v = int(text)
    except ValueError:
        raise _argparse.ArgumentTypeError(f"invalid integer: {text!r}")
    if v < 1:
        raise _argparse.ArgumentTypeError("--top must be >= 1")
    return v


def main(argv: list[str] | None = None) -> int:
    """CLI entry point. Returns the process exit code."""
    parser = _Parser(prog="logstats.py", description="Access log analyzer")
    parser.add_argument("logfile")
    parser.add_argument("--top", type=_positive_int, default=5)
    parser.add_argument("--format", choices=["json", "table"], default="json")
    parser.add_argument("--strict", action="store_true")
    try:
        args = parser.parse_args(argv)
    except SystemExit as e:
        return e.code if isinstance(e.code, int) else 2

    try:
        with open(args.logfile, encoding="utf-8", errors="replace") as fh:
            lines = list(fh)
    except OSError as e:
        _sys.stderr.write(f"cannot read {args.logfile}: {e}\n")
        return 2

    if args.strict:
        for n, line in enumerate(lines, 1):
            if line.strip() and parse_line(line) is None:
                _sys.stderr.write(f"malformed line {n}: {line.rstrip(chr(10)).rstrip(chr(13))}\n")
                return 2

    report = analyze(lines, top=args.top)
    if args.format == "json":
        _sys.stdout.write(_json.dumps(report, indent=2) + "\n")
    else:
        _sys.stdout.write(_format_table(report))
    return 0


if __name__ == "__main__":
    _sys.exit(main())
