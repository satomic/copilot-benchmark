"""Tests for the access-log analyzer. Fixtures are inline or tmp_path only."""

import json
from datetime import datetime, timedelta, timezone

from logstats import analyze, main, parse_line

_LINE = (
    '203.0.113.10 - - [09/Sep/2026:08:00:01 +0800] '
    '"GET /api/users HTTP/1.1" 200 1024 0.042'
)


def _line(ip="1.1.1.1", user="-", method="GET", path="/a", status=200, nbytes="1", duration="1.0", second="01"):
    return (
        f'{ip} - {user} [09/Sep/2026:08:00:{second} +0800] '
        f'"{method} {path} HTTP/1.1" {status} {nbytes} {duration}'
    )


def test_parse_well_formed_line_field_by_field():
    rec = parse_line(_LINE)
    assert rec == {
        "ip": "203.0.113.10",
        "user": None,
        "timestamp": datetime(2026, 9, 9, 8, 0, 1, tzinfo=timezone(timedelta(hours=8))),
        "method": "GET",
        "path": "/api/users",
        "protocol": "HTTP/1.1",
        "status": 200,
        "bytes": 1024,
        "duration": 0.042,
    }
    assert rec["timestamp"].utcoffset().total_seconds() == 8 * 3600


def test_malformed_line_returns_none():
    assert parse_line("this line is not a log line at all") is None
    assert parse_line('1.2.3.4 - - [09/Sep/2026:08:00:01 +0800] "GET / HTTP/1.1" 200 1 abc') is None
    assert parse_line("256.1.1.1 - - [09/Sep/2026:08:00:01 +0800] \"GET / HTTP/1.1\" 200 1 0.1") is None


def test_bytes_dash_becomes_zero_and_named_user_kept():
    rec = parse_line(
        '198.51.100.7 - alice [09/Sep/2026:08:00:03 +0800] "GET / HTTP/1.1" 304 - 0.011'
    )
    assert rec is not None
    assert rec["bytes"] == 0
    assert rec["user"] == "alice"


def test_user_dash_becomes_none():
    rec = parse_line(_LINE)
    assert rec is not None
    assert rec["user"] is None


def test_parse_line_strips_trailing_terminator():
    assert parse_line(_LINE + "\n") == parse_line(_LINE)
    assert parse_line(_LINE + "\r\n") == parse_line(_LINE)


def test_percentile_nearest_rank():
    report = analyze([
        _line(duration="1.0", second="01"),
        _line(duration="2.0", second="02"),
        _line(duration="3.0", second="03"),
        _line(duration="4.0", second="04"),
    ])
    assert report["duration"]["count"] == 4
    assert report["duration"]["p50"] == 2.0
    assert report["duration"]["p95"] == 4.0
    assert report["duration"]["mean"] == 2.5
    assert report["duration"]["max"] == 4.0
    assert report["status_classes"] == {"2xx": 4, "3xx": 0, "4xx": 0, "5xx": 0, "other": 0}

    empty = analyze(["   \n", "\n", "not a log"])
    assert empty["lines_total"] == 1
    assert empty["lines_parsed"] == 0
    assert empty["lines_malformed"] == 1
    assert empty["duration"] == {"count": 0, "mean": 0.0, "p50": 0.0, "p95": 0.0, "max": 0.0}


def test_top_truncation_and_tie_breaking():
    lines = [
        _line(ip="2.2.2.2", path="/b", second="01"),
        _line(ip="2.2.2.2", path="/b", second="02"),
        _line(ip="1.1.1.1", path="/a", second="03"),
        _line(ip="1.1.1.1", path="/a", second="04"),
        _line(ip="3.3.3.3", path="/c", second="05"),
    ]
    report = analyze(lines, top=2)
    assert report["top_paths"] == [
        {"path": "/a", "count": 2},
        {"path": "/b", "count": 2},
    ]
    assert report["top_ips"] == [
        {"ip": "1.1.1.1", "count": 2},
        {"ip": "2.2.2.2", "count": 2},
    ]
    truncated = analyze(lines, top=1)
    assert truncated["top_paths"] == [{"path": "/a", "count": 2}]
    assert truncated["top_ips"] == [{"ip": "1.1.1.1", "count": 2}]


def test_status_classes_methods_and_bytes():
    report = analyze([
        _line(method="GET", status=100, nbytes="5", second="01"),
        _line(method="POST", status=301, nbytes="7", second="02"),
        _line(method="DELETE", status=404, nbytes="-", second="03"),
        _line(method="GET", status=503, nbytes="3", second="04"),
        _line(method="GET", status=600, nbytes="1", second="05"),
        "   ",
        "garbage",
    ])
    assert report["lines_total"] == 6
    assert report["lines_parsed"] == 5
    assert report["lines_malformed"] == 1
    assert report["bytes_total"] == 16
    assert report["status_classes"] == {"2xx": 0, "3xx": 1, "4xx": 1, "5xx": 1, "other": 2}
    assert list(report["methods"]) == ["DELETE", "GET", "POST"]
    assert report["methods"] == {"DELETE": 1, "GET": 3, "POST": 1}


def test_strict_exits_2(tmp_path, capsys):
    path = tmp_path / "access.log"
    path.write_text("\n   \nnot a log line\n" + _LINE + "\n", encoding="utf-8")
    code = main([str(path), "--strict", "--format", "table"])
    captured = capsys.readouterr()
    assert code == 2
    assert captured.out == ""
    assert captured.err == "malformed line 3: not a log line\n"


def test_missing_file_exits_2(tmp_path, capsys):
    missing = tmp_path / "no-such-log.txt"
    code = main([str(missing)])
    captured = capsys.readouterr()
    assert code == 2
    assert captured.out == ""
    assert "error:" in captured.err


def test_top_usage_error(tmp_path, capsys):
    path = tmp_path / "access.log"
    path.write_text(_LINE + "\n", encoding="utf-8")
    for bad in ("0", "-3", "foo", "1.5"):
        code = main([str(path), "--top", bad])
        captured = capsys.readouterr()
        assert code == 2
        assert captured.out == ""
        assert captured.err != ""


def test_cli_json_and_table(tmp_path, capsys):
    path = tmp_path / "access.log"
    body = _LINE + "\n" + "bad line\n"
    path.write_text(body, encoding="utf-8")
    code = main([str(path), "--top", "1"])
    captured = capsys.readouterr()
    assert code == 0
    report = json.loads(captured.out)
    assert report["lines_total"] == 2
    assert report["lines_parsed"] == 1
    assert report["lines_malformed"] == 1
    assert report["top_paths"] == [{"path": "/api/users", "count": 1}]
    assert captured.out.endswith("\n")

    code = main([str(path), "--format", "table"])
    captured = capsys.readouterr()
    assert code == 0
    text = captured.out
    for token in ("lines_total", "status_classes", "top_paths", "top_ips", "duration"):
        assert token in text
    try:
        json.loads(text)
        valid_json = True
    except json.JSONDecodeError:
        valid_json = False
    assert not valid_json


def test_negative_timezone_offset():
    rec = parse_line(
        '10.0.0.5 - bob [09/Sep/2026:08:00:01 -0530] "HEAD /health HTTP/1.0" 204 - 0'
    )
    assert rec is not None
    assert rec["user"] == "bob"
    assert rec["method"] == "HEAD"
    assert rec["protocol"] == "HTTP/1.0"
    assert rec["bytes"] == 0
    assert rec["duration"] == 0.0
    assert rec["timestamp"].utcoffset().total_seconds() == -(5 * 3600 + 30 * 60)
