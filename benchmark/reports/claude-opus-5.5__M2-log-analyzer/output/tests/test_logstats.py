import datetime as dt
import json

import pytest

import logstats
from logstats import analyze, main, parse_line

GOOD = '203.0.113.10 - - [09/Sep/2026:08:00:01 +0800] "GET /api/users HTTP/1.1" 200 1024 0.042'


def _line(ip="1.1.1.1", path="/a", status=200, nbytes="1", duration="0.1",
          method="GET", user="-"):
    return (f'{ip} - {user} [09/Sep/2026:08:00:01 +0800] '
            f'"{method} {path} HTTP/1.1" {status} {nbytes} {duration}')


def test_parse_well_formed_line_field_by_field():
    rec = parse_line(GOOD)
    assert set(rec) == {"ip", "user", "timestamp", "method", "path",
                        "protocol", "status", "bytes", "duration"}
    assert rec["ip"] == "203.0.113.10"
    assert rec["user"] is None
    assert rec["timestamp"] == dt.datetime(
        2026, 9, 9, 8, 0, 1, tzinfo=dt.timezone(dt.timedelta(hours=8)))
    assert rec["timestamp"].utcoffset().total_seconds() == 8 * 3600
    assert rec["method"] == "GET"
    assert rec["path"] == "/api/users"
    assert rec["protocol"] == "HTTP/1.1"
    assert rec["status"] == 200 and isinstance(rec["status"], int)
    assert rec["bytes"] == 1024
    assert rec["duration"] == 0.042


@pytest.mark.parametrize("suffix", ["\n", "\r\n"])
def test_parse_tolerates_trailing_newline(suffix):
    assert parse_line(GOOD + suffix) == parse_line(GOOD)


@pytest.mark.parametrize("bad", [
    "this line is not a log line at all",
    '"GET /orphan HTTP/1.1" 200 100 0.010',
    '10.0.0.5 - - [09/Sep/2026:08:00:53 BAD] "GET /admin HTTP/1.1" 403 64 0.005',
    _line(duration="abc"),
    _line(ip="999.1.1.1"),
    GOOD + " extra",
    '1.1.1.1 - - [31/Feb/2026:08:00:01 +0800] "GET / HTTP/1.1" 200 1 0.1',
])
def test_malformed_line_returns_none(bad):
    assert parse_line(bad) is None


def test_dash_bytes_become_zero_and_named_user_kept():
    rec = parse_line(
        '198.51.100.7 - alice [09/Sep/2026:08:00:03 +0800] "GET / HTTP/1.1" 304 - 0.011')
    assert rec["bytes"] == 0
    assert rec["user"] == "alice"


def test_dash_user_becomes_none():
    assert parse_line(_line(user="-"))["user"] is None
    assert parse_line(_line(user="bob"))["user"] == "bob"


def test_percentile_nearest_rank():
    lines = [_line(duration=d) for d in ("4.0", "1.0", "3.0", "2.0")]
    d = analyze(lines)["duration"]
    assert d == {"count": 4, "mean": 2.5, "p50": 2.0, "p95": 4.0, "max": 4.0}
    # n=20: p95 index = ceil(19) - 1 = 18 -> 19th value
    d20 = analyze([_line(duration=str(i)) for i in range(1, 21)])["duration"]
    assert d20["p50"] == 10.0 and d20["p95"] == 19.0
    # n=1: indexes clamp to 0
    d1 = analyze([_line(duration="0.5")])["duration"]
    assert d1["p50"] == d1["p95"] == d1["max"] == 0.5


def test_top_truncation_and_tie_breaking():
    lines = (
        [_line(path="/b", ip="2.2.2.2")] * 2
        + [_line(path="/a", ip="1.1.1.1")] * 2
        + [_line(path="/c", ip="3.3.3.3")] * 3
        + [_line(path="/d", ip="4.4.4.4")]
    )
    r = analyze(lines, top=3)
    assert r["top_paths"] == [
        {"path": "/c", "count": 3},
        {"path": "/a", "count": 2},
        {"path": "/b", "count": 2},
    ]
    assert r["top_ips"] == [
        {"ip": "3.3.3.3", "count": 3},
        {"ip": "1.1.1.1", "count": 2},
        {"ip": "2.2.2.2", "count": 2},
    ]
    assert len(analyze(lines, top=1)["top_paths"]) == 1


def test_analyze_report_structure_and_counts():
    lines = [
        _line(status=200, nbytes="10", method="POST"),
        _line(status=301, nbytes="-"),
        _line(status=404, nbytes="5"),
        _line(status=503, nbytes="1"),
        _line(status=199, nbytes="1"),
        _line(status=600, nbytes="1"),
        "garbage",
        "",
        "   \n",
    ]
    r = analyze(lines)
    assert list(r) == ["lines_total", "lines_parsed", "lines_malformed", "bytes_total",
                       "status_classes", "methods", "top_paths", "top_ips", "duration"]
    assert r["lines_total"] == 7
    assert r["lines_parsed"] == 6
    assert r["lines_malformed"] == 1
    assert r["bytes_total"] == 18
    assert r["status_classes"] == {"2xx": 1, "3xx": 1, "4xx": 1, "5xx": 1, "other": 2}
    assert list(r["methods"].items()) == [("GET", 5), ("POST", 1)]


def test_analyze_empty_input():
    r = analyze(["", "bad"])
    assert r["lines_total"] == 1 and r["lines_parsed"] == 0
    assert r["duration"] == {"count": 0, "mean": 0.0, "p50": 0.0, "p95": 0.0, "max": 0.0}
    assert r["status_classes"] == {"2xx": 0, "3xx": 0, "4xx": 0, "5xx": 0, "other": 0}
    assert r["methods"] == {} and r["top_paths"] == [] and r["top_ips"] == []


def _write(tmp_path, lines):
    p = tmp_path / "access.log"
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return p


def test_cli_json_output(tmp_path, capsys):
    p = _write(tmp_path, [_line(path="/x"), "bad", _line(path="/y")])
    assert main([str(p), "--top", "1"]) == 0
    out, err = capsys.readouterr()
    report = json.loads(out)
    assert out == json.dumps(report, indent=2) + "\n"
    assert report["lines_total"] == 3 and report["lines_malformed"] == 1
    assert len(report["top_paths"]) == 1


def test_cli_table_output(tmp_path, capsys):
    p = _write(tmp_path, [_line()])
    assert main([str(p), "--format", "table"]) == 0
    out, _ = capsys.readouterr()
    for key in ("lines_total", "status_classes", "top_paths", "top_ips", "duration"):
        assert key in out
    with pytest.raises(ValueError):
        json.loads(out)


def test_cli_strict_exits_2_on_first_malformed(tmp_path, capsys):
    p = _write(tmp_path, [_line(), "", "first bad", "second bad"])
    assert main([str(p), "--strict"]) == 2
    out, err = capsys.readouterr()
    assert out == ""
    assert err.strip() == "malformed line 3: first bad"


def test_cli_strict_passes_clean_file(tmp_path, capsys):
    p = _write(tmp_path, [_line()])
    assert main([str(p), "--strict"]) == 0


def test_cli_missing_file_exits_2(tmp_path, capsys):
    assert main([str(tmp_path / "missing.log")]) == 2
    out, err = capsys.readouterr()
    assert out == "" and err


@pytest.mark.parametrize("value", ["0", "-1", "abc", "1.5"])
def test_cli_bad_top_is_usage_error(tmp_path, capsys, value):
    p = _write(tmp_path, [_line()])
    assert main([str(p), "--top", value]) == 2
    out, err = capsys.readouterr()
    assert out == "" and err


def test_public_api_only():
    public = {n for n in vars(logstats) if not n.startswith("_")}
    assert public == {"parse_line", "analyze", "main"}
