"""Access log parser and statistics analyzer."""

import argparse as _argparse
from collections import Counter as _Counter
from collections.abc import Iterable as _Iterable
from datetime import datetime as _datetime, timezone as _timezone, timedelta as _timedelta
import json as _json
import math as _math
import re as _re
import sys as _sys

__all__ = ["parse_line", "analyze", "main"]

_MONTHS: dict[str, int] = {
    "Jan": 1, "Feb": 2, "Mar": 3, "Apr": 4, "May": 5, "Jun": 6,
    "Jul": 7, "Aug": 8, "Sep": 9, "Oct": 10, "Nov": 11, "Dec": 12,
}

_LINE_RE = _re.compile(
    r"^(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}) "
    r"- "
    r"(-|[a-zA-Z0-9_]+) "
    r"\[([^\]]+)\] "
    r"\"([A-Z]+) ([^ \t\r\n\"]+) ([^ \t\r\n\"]+)\" "
    r"(\d{3}) "
    r"(-|\d+) "
    r"(\d+(?:\.\d+)?)$"
)

_TS_RE = _re.compile(
    r"^(\d{2})/([A-Za-z]{3})/(\d{4}):(\d{2}):(\d{2}):(\d{2}) ([+-])(\d{2})(\d{2})$"
)


class _UsageError(Exception):
    """Raised when command-line arguments are invalid."""
    pass


class _NoExitArgumentParser(_argparse.ArgumentParser):
    """ArgumentParser that raises _UsageError on error instead of calling sys.exit()."""

    def error(self, message: str) -> None:
        _sys.stderr.write(f"error: {message}\n")
        raise _UsageError(message)


def _parse_timestamp(ts_raw: str) -> _datetime | None:
    tm = _TS_RE.match(ts_raw)
    if not tm:
        return None
    day_str, mon_str, year_str, hr_str, mn_str, sc_str, tz_sign, tz_hr_str, tz_min_str = tm.groups()
    if mon_str not in _MONTHS:
        return None
    month = _MONTHS[mon_str]
    tz_h = int(tz_hr_str)
    tz_m = int(tz_min_str)
    if tz_m >= 60 or tz_h > 23:
        return None
    offset_mins = (tz_h * 60 + tz_m) * (-1 if tz_sign == "-" else 1)
    tz = _timezone(_timedelta(minutes=offset_mins))
    try:
        return _datetime(int(year_str), month, int(day_str), int(hr_str), int(mn_str), int(sc_str), tzinfo=tz)
    except ValueError:
        return None


def parse_line(line: str) -> dict | None:
    """Return a record dict, or None when the line is malformed."""
    if not isinstance(line, str):
        return None

    # Strip line terminator: <line>\n or <line>\r\n or <line>\r
    if line.endswith("\r\n"):
        line = line[:-2]
    elif line.endswith("\n") or line.endswith("\r"):
        line = line[:-1]

    m = _LINE_RE.match(line)
    if not m:
        return None

    ip, user, ts_raw, method, path, proto, status, b_raw, dur_raw = m.groups()

    # Validate IPv4 dotted-quad octets (0-255)
    parts = ip.split(".")
    if not all(0 <= int(p) <= 255 for p in parts):
        return None

    # Validate timestamp
    dt = _parse_timestamp(ts_raw)
    if dt is None:
        return None

    return {
        "ip": ip,
        "user": None if user == "-" else user,
        "timestamp": dt,
        "method": method,
        "path": path,
        "protocol": proto,
        "status": int(status),
        "bytes": 0 if b_raw == "-" else int(b_raw),
        "duration": float(dur_raw),
    }


def analyze(lines: _Iterable[str], top: int = 5) -> dict:
    """Aggregate an iterable of raw log lines into the report structure."""
    lines_total = 0
    lines_parsed = 0
    lines_malformed = 0
    bytes_total = 0
    status_classes: dict[str, int] = {"2xx": 0, "3xx": 0, "4xx": 0, "5xx": 0, "other": 0}
    methods: _Counter[str] = _Counter()
    paths: _Counter[str] = _Counter()
    ips: _Counter[str] = _Counter()
    durations: list[float] = []

    for raw_line in lines:
        line = raw_line.rstrip("\r\n")
        if not line.strip():
            # Blank lines (empty or whitespace-only) are ignored entirely
            continue
        lines_total += 1
        rec = parse_line(raw_line)
        if rec is None:
            lines_malformed += 1
            continue
        lines_parsed += 1
        bytes_total += rec["bytes"]
        st = rec["status"]
        if 200 <= st < 300:
            status_classes["2xx"] += 1
        elif 300 <= st < 400:
            status_classes["3xx"] += 1
        elif 400 <= st < 500:
            status_classes["4xx"] += 1
        elif 500 <= st < 600:
            status_classes["5xx"] += 1
        else:
            status_classes["other"] += 1

        methods[rec["method"]] += 1
        paths[rec["path"]] += 1
        ips[rec["ip"]] += 1
        durations.append(rec["duration"])

    sorted_methods = dict(sorted(methods.items()))

    limit = max(0, top)
    sorted_paths = sorted(paths.items(), key=lambda x: (-x[1], x[0]))
    top_paths = [{"path": p, "count": c} for p, c in sorted_paths[:limit]]

    sorted_ips = sorted(ips.items(), key=lambda x: (-x[1], x[0]))
    top_ips = [{"ip": ip, "count": c} for ip, c in sorted_ips[:limit]]

    if not durations:
        duration_stats = {
            "count": 0,
            "mean": 0.0,
            "p50": 0.0,
            "p95": 0.0,
            "max": 0.0,
        }
    else:
        n = len(durations)
        sorted_durs = sorted(durations)

        def _calc_p(p: float) -> float:
            idx = _math.ceil((p / 100.0) * n) - 1
            idx = max(0, min(idx, n - 1))
            return sorted_durs[idx]

        duration_stats = {
            "count": n,
            "mean": round(sum(sorted_durs) / n, 3),
            "p50": round(_calc_p(50.0), 3),
            "p95": round(_calc_p(95.0), 3),
            "max": round(sorted_durs[-1], 3),
        }

    return {
        "lines_total": lines_total,
        "lines_parsed": lines_parsed,
        "lines_malformed": lines_malformed,
        "bytes_total": bytes_total,
        "status_classes": status_classes,
        "methods": sorted_methods,
        "top_paths": top_paths,
        "top_ips": top_ips,
        "duration": duration_stats,
    }


def _format_table(report: dict) -> str:
    """Format report dict into human-readable text."""
    lines = [
        f"lines_total:     {report['lines_total']} (parsed: {report['lines_parsed']}, malformed: {report['lines_malformed']})",
        f"bytes_total:     {report['bytes_total']}",
        "status_classes:",
    ]
    for sc, count in report["status_classes"].items():
        lines.append(f"  {sc}: {count}")
    lines.append("methods:")
    for method, count in report["methods"].items():
        lines.append(f"  {method}: {count}")
    lines.append("top_paths:")
    for item in report["top_paths"]:
        lines.append(f"  {item['path']}: {item['count']}")
    lines.append("top_ips:")
    for item in report["top_ips"]:
        lines.append(f"  {item['ip']}: {item['count']}")
    lines.append("duration:")
    for k, v in report["duration"].items():
        lines.append(f"  {k}: {v}")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    """CLI entry point. Returns the process exit code."""
    if argv is None:
        argv = _sys.argv[1:]

    parser = _NoExitArgumentParser(prog="logstats")
    parser.add_argument("logfile")
    parser.add_argument("--top", default="5")
    parser.add_argument("--format", choices=["json", "table"], default="json")
    parser.add_argument("--strict", action="store_true")

    try:
        args = parser.parse_args(argv)
    except _UsageError:
        return 2
    except SystemExit as e:
        return e.code if isinstance(e.code, int) else 0

    # Validate --top
    try:
        top_val = int(args.top)
        if top_val < 1:
            raise ValueError()
    except ValueError:
        _sys.stderr.write("error: --top must be an integer >= 1\n")
        return 2

    # Open logfile
    try:
        with open(args.logfile, "r", encoding="utf-8", errors="replace") as f:
            if args.strict:
                valid_lines: list[str] = []
                for lineno, raw_line in enumerate(f, start=1):
                    line = raw_line.rstrip("\r\n")
                    if not line.strip():
                        continue
                    rec = parse_line(raw_line)
                    if rec is None:
                        _sys.stderr.write(f"malformed line {lineno}: {line}\n")
                        return 2
                    valid_lines.append(raw_line)
                report = analyze(valid_lines, top=top_val)
            else:
                report = analyze(f, top=top_val)
    except OSError as e:
        _sys.stderr.write(f"error: cannot read log file '{args.logfile}': {e}\n")
        return 2

    if args.format == "json":
        _sys.stdout.write(_json.dumps(report, indent=2) + "\n")
    else:
        _sys.stdout.write(_format_table(report))

    return 0


if __name__ == "__main__":
    _sys.exit(main())
