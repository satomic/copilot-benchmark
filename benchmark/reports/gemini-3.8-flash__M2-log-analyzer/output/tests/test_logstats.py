"""Test suite for logstats library and CLI."""

from datetime import datetime, timezone, timedelta
import json
import pytest

import logstats
from logstats import parse_line, analyze, main


def test_parse_line_well_formed_field_by_field():
    line = '203.0.113.10 - alice [09/Sep/2026:08:00:01 +0800] "GET /api/users HTTP/1.1" 200 1024 0.042\n'
    rec = parse_line(line)
    assert rec is not None
    assert rec["ip"] == "203.0.113.10"
    assert rec["user"] == "alice"
    assert isinstance(rec["timestamp"], datetime)
    assert rec["timestamp"].tzinfo is not None
    assert rec["timestamp"].utcoffset() == timedelta(hours=8)
    assert rec["timestamp"].year == 2026
    assert rec["timestamp"].month == 9
    assert rec["timestamp"].day == 9
    assert rec["timestamp"].hour == 8
    assert rec["timestamp"].minute == 0
    assert rec["timestamp"].second == 1
    assert rec["method"] == "GET"
    assert rec["path"] == "/api/users"
    assert rec["protocol"] == "HTTP/1.1"
    assert rec["status"] == 200
    assert rec["bytes"] == 1024
    assert rec["duration"] == 0.042

    # CRLF line terminator
    line_crlf = '10.0.0.1 - - [01/Jan/2025:00:00:00 -0500] "POST /login HTTP/2.0" 201 0 1.250\r\n'
    rec_crlf = parse_line(line_crlf)
    assert rec_crlf is not None
    assert rec_crlf["ip"] == "10.0.0.1"
    assert rec_crlf["user"] is None
    assert rec_crlf["timestamp"].utcoffset() == timedelta(hours=-5)
    assert rec_crlf["method"] == "POST"
    assert rec_crlf["path"] == "/login"
    assert rec_crlf["protocol"] == "HTTP/2.0"
    assert rec_crlf["status"] == 201
    assert rec_crlf["bytes"] == 0
    assert rec_crlf["duration"] == 1.25


def test_parse_line_malformed_returns_none():
    # Non-string input
    assert parse_line(123) is None  # type: ignore

    # Total garbage
    assert parse_line("this line is not a log line at all") is None

    # Invalid IP octets
    assert parse_line('999.0.0.1 - - [09/Sep/2026:08:00:01 +0800] "GET / HTTP/1.1" 200 100 0.1') is None
    assert parse_line('1.2.3.4.5 - - [09/Sep/2026:08:00:01 +0800] "GET / HTTP/1.1" 200 100 0.1') is None

    # Invalid timestamp (month, timezone, day)
    assert parse_line('1.1.1.1 - - [09/Bad/2026:08:00:01 +0800] "GET / HTTP/1.1" 200 100 0.1') is None
    assert parse_line('1.1.1.1 - - [09/Sep/2026:08:00:01 BADTZ] "GET / HTTP/1.1" 200 100 0.1') is None
    assert parse_line('1.1.1.1 - - [32/Sep/2026:08:00:01 +0800] "GET / HTTP/1.1" 200 100 0.1') is None

    # Missing quotes / bad request shape
    assert parse_line('1.1.1.1 - - [09/Sep/2026:08:00:01 +0800] GET / HTTP/1.1 200 100 0.1') is None
    assert parse_line('"GET /orphan HTTP/1.1" 200 100 0.010') is None

    # Invalid status
    assert parse_line('1.1.1.1 - - [09/Sep/2026:08:00:01 +0800] "GET / HTTP/1.1" 20 100 0.1') is None
    assert parse_line('1.1.1.1 - - [09/Sep/2026:08:00:01 +0800] "GET / HTTP/1.1" 2000 100 0.1') is None

    # Invalid bytes
    assert parse_line('1.1.1.1 - - [09/Sep/2026:08:00:01 +0800] "GET / HTTP/1.1" 200 abc 0.1') is None

    # Invalid duration
    assert parse_line('1.1.1.1 - - [09/Sep/2026:08:00:01 +0800] "GET / HTTP/1.1" 200 100 abc') is None

    # Trailing spaces after well-formed content
    assert parse_line('1.1.1.1 - - [09/Sep/2026:08:00:01 +0800] "GET / HTTP/1.1" 200 100 0.1   ') is None


def test_parse_line_bytes_dash_becomes_zero():
    line = '198.51.100.7 - alice [09/Sep/2026:08:00:03 +0800] "GET / HTTP/1.1" 304 - 0.011'
    rec = parse_line(line)
    assert rec is not None
    assert rec["bytes"] == 0

    line2 = '198.51.100.7 - alice [09/Sep/2026:08:00:03 +0800] "GET / HTTP/1.1" 200 5000 0.011'
    rec2 = parse_line(line2)
    assert rec2 is not None
    assert rec2["bytes"] == 5000


def test_parse_line_user_dash_becomes_none():
    line_anon = '198.51.100.7 - - [09/Sep/2026:08:00:03 +0800] "GET / HTTP/1.1" 200 100 0.011'
    rec_anon = parse_line(line_anon)
    assert rec_anon is not None
    assert rec_anon["user"] is None

    line_user = '198.51.100.7 - bob_12 [09/Sep/2026:08:00:03 +0800] "GET / HTTP/1.1" 200 100 0.011'
    rec_user = parse_line(line_user)
    assert rec_user is not None
    assert rec_user["user"] == "bob_12"


def test_duration_percentiles_and_statistics():
    # Empty input
    r_empty = analyze([])
    assert r_empty["lines_total"] == 0
    assert r_empty["lines_parsed"] == 0
    assert r_empty["lines_malformed"] == 0
    assert r_empty["bytes_total"] == 0
    assert r_empty["duration"] == {
        "count": 0,
        "mean": 0.0,
        "p50": 0.0,
        "p95": 0.0,
        "max": 0.0,
    }

    # Single value
    r_single = analyze([
        '1.1.1.1 - - [09/Sep/2026:08:00:01 +0800] "GET /a HTTP/1.1" 200 10 0.1236'
    ])
    assert r_single["duration"] == {
        "count": 1,
        "mean": 0.124,
        "p50": 0.124,
        "p95": 0.124,
        "max": 0.124,
    }

    # Four values: nearest rank nearest-rank test from acceptance criteria
    # n=4: p50 index ceil(0.5*4)-1 = 1; p95 index ceil(0.95*4)-1 = 3
    lines_4 = [
        '1.1.1.1 - - [09/Sep/2026:08:00:01 +0800] "GET /a HTTP/1.1" 200 1 1.0',
        '1.1.1.1 - - [09/Sep/2026:08:00:02 +0800] "GET /a HTTP/1.1" 200 1 2.0',
        '1.1.1.1 - - [09/Sep/2026:08:00:03 +0800] "GET /a HTTP/1.1" 200 1 3.0',
        '1.1.1.1 - - [09/Sep/2026:08:00:04 +0800] "GET /a HTTP/1.1" 200 1 4.0',
    ]
    r_4 = analyze(lines_4)
    assert r_4["duration"]["count"] == 4
    assert r_4["duration"]["mean"] == 2.5
    assert r_4["duration"]["p50"] == 2.0
    assert r_4["duration"]["p95"] == 4.0
    assert r_4["duration"]["max"] == 4.0


def test_top_truncation_and_tie_breaking():
    # Tie breaking: count descending, then string ascending
    lines = [
        '10.0.0.2 - - [09/Sep/2026:08:00:01 +0800] "GET /pathB HTTP/1.1" 200 1 0.1',
        '10.0.0.2 - - [09/Sep/2026:08:00:02 +0800] "GET /pathB HTTP/1.1" 200 1 0.1',
        '10.0.0.1 - - [09/Sep/2026:08:00:03 +0800] "GET /pathA HTTP/1.1" 200 1 0.1',
        '10.0.0.1 - - [09/Sep/2026:08:00:04 +0800] "GET /pathA HTTP/1.1" 200 1 0.1',
        '10.0.0.3 - - [09/Sep/2026:08:00:05 +0800] "GET /pathC HTTP/1.1" 200 1 0.1',
    ]
    # With top=2:
    # /pathA (count 2) and /pathB (count 2) tie -> /pathA comes first
    # 10.0.0.1 (count 2) and 10.0.0.2 (count 2) tie -> 10.0.0.1 comes first
    report = analyze(lines, top=2)
    assert report["top_paths"] == [
        {"path": "/pathA", "count": 2},
        {"path": "/pathB", "count": 2},
    ]
    assert report["top_ips"] == [
        {"ip": "10.0.0.1", "count": 2},
        {"ip": "10.0.0.2", "count": 2},
    ]


def test_analyze_status_classes_methods_and_blank_lines():
    lines = [
        "",  # blank line
        "   \n",  # whitespace line
        '1.1.1.1 - - [09/Sep/2026:08:00:01 +0800] "GET / HTTP/1.1" 101 10 0.1',  # other (< 200)
        '1.1.1.1 - - [09/Sep/2026:08:00:02 +0800] "POST / HTTP/1.1" 200 20 0.1',  # 2xx
        '1.1.1.1 - - [09/Sep/2026:08:00:03 +0800] "GET / HTTP/1.1" 301 30 0.1',   # 3xx
        '1.1.1.1 - - [09/Sep/2026:08:00:04 +0800] "HEAD / HTTP/1.1" 404 40 0.1',  # 4xx
        '1.1.1.1 - - [09/Sep/2026:08:00:05 +0800] "PUT / HTTP/1.1" 503 50 0.1',   # 5xx
        '1.1.1.1 - - [09/Sep/2026:08:00:06 +0800] "GET / HTTP/1.1" 600 60 0.1',   # other (>= 600)
        "malformed line here",
        "  \t  \r\n",  # blank line
    ]
    report = analyze(lines)
    assert report["lines_total"] == 7  # 6 parsed + 1 malformed (blanks ignored)
    assert report["lines_parsed"] == 6
    assert report["lines_malformed"] == 1
    assert report["bytes_total"] == 210
    assert report["status_classes"] == {
        "2xx": 1,
        "3xx": 1,
        "4xx": 1,
        "5xx": 1,
        "other": 2,
    }
    # Methods sorted ascending, only seen methods
    assert list(report["methods"].keys()) == ["GET", "HEAD", "POST", "PUT"]
    assert report["methods"] == {"GET": 3, "HEAD": 1, "POST": 1, "PUT": 1}


def test_cli_strict_exiting_2_on_first_malformed(tmp_path, capsys):
    log_file = tmp_path / "test.log"
    content = (
        '1.1.1.1 - - [09/Sep/2026:08:00:01 +0800] "GET / HTTP/1.1" 200 10 0.1\n'
        "\n"  # blank line
        "this is malformed\n"
        '1.1.1.1 - - [09/Sep/2026:08:00:02 +0800] "GET / HTTP/1.1" 200 10 0.1\n'
    )
    log_file.write_text(content, encoding="utf-8")

    code = main([str(log_file), "--strict"])
    out, err = capsys.readouterr()

    assert code == 2
    assert out == ""
    assert err == "malformed line 3: this is malformed\n"


def test_cli_missing_or_unreadable_file_exiting_2(capsys):
    code = main(["non_existent_file_definitely_not_here.log"])
    out, err = capsys.readouterr()

    assert code == 2
    assert out == ""
    assert "error: cannot read log file" in err


def test_cli_invalid_top_exiting_2(tmp_path, capsys):
    log_file = tmp_path / "empty.log"
    log_file.write_text("", encoding="utf-8")

    # top < 1
    code_zero = main([str(log_file), "--top", "0"])
    out, err = capsys.readouterr()
    assert code_zero == 2
    assert out == ""
    assert "error: --top must be an integer >= 1" in err

    # top negative
    code_neg = main([str(log_file), "--top", "-3"])
    out, err = capsys.readouterr()
    assert code_neg == 2
    assert out == ""

    # top not int
    code_abc = main([str(log_file), "--top", "abc"])
    out, err = capsys.readouterr()
    assert code_abc == 2
    assert out == ""


def test_cli_format_json_and_table(tmp_path, capsys):
    log_file = tmp_path / "simple.log"
    log_file.write_text(
        '1.1.1.1 - - [09/Sep/2026:08:00:01 +0800] "GET /test HTTP/1.1" 200 100 0.05\n',
        encoding="utf-8",
    )

    # JSON format (default)
    code_json = main([str(log_file)])
    out_json, err_json = capsys.readouterr()
    assert code_json == 0
    assert err_json == ""
    assert out_json.endswith("\n")
    data = json.loads(out_json)
    assert data["lines_total"] == 1
    assert data["lines_parsed"] == 1
    assert data["lines_malformed"] == 0

    # Table format
    code_table = main([str(log_file), "--format", "table"])
    out_table, err_table = capsys.readouterr()
    assert code_table == 0
    assert err_table == ""
    for required_substr in ["lines_total", "status_classes", "top_paths", "top_ips", "duration"]:
        assert required_substr in out_table
    with pytest.raises(json.JSONDecodeError):
        json.loads(out_table)


def test_acceptance_criteria_sample_data():
    rec = parse_line(
        '203.0.113.10 - - [09/Sep/2026:08:00:01 +0800] "GET /api/users HTTP/1.1" 200 1024 0.042'
    )
    assert rec["ip"] == "203.0.113.10"
    assert rec["user"] is None
    assert rec["method"] == "GET" and rec["path"] == "/api/users"
    assert rec["status"] == 200 and rec["bytes"] == 1024
    assert rec["duration"] == 0.042
    assert rec["timestamp"].utcoffset().total_seconds() == 8 * 3600

    assert parse_line("this line is not a log line at all") is None

    # `-` bytes become 0, named user is kept
    rec2 = parse_line(
        '198.51.100.7 - alice [09/Sep/2026:08:00:03 +0800] "GET / HTTP/1.1" 304 - 0.011'
    )
    assert rec2["bytes"] == 0 and rec2["user"] == "alice"

    # nearest-rank percentile: n=4, p50 -> index ceil(0.5*4)-1 = 1
    r = analyze([
        '1.1.1.1 - - [09/Sep/2026:08:00:01 +0800] "GET /a HTTP/1.1" 200 1 1.0',
        '1.1.1.1 - - [09/Sep/2026:08:00:02 +0800] "GET /a HTTP/1.1" 200 1 2.0',
        '1.1.1.1 - - [09/Sep/2026:08:00:03 +0800] "GET /a HTTP/1.1" 200 1 3.0',
        '1.1.1.1 - - [09/Sep/2026:08:00:04 +0800] "GET /a HTTP/1.1" 200 1 4.0',
    ])
    assert r["duration"]["p50"] == 2.0
    assert r["duration"]["p95"] == 4.0
    assert r["status_classes"] == {"2xx": 4, "3xx": 0, "4xx": 0, "5xx": 0, "other": 0}


def test_private_symbols_and_public_api():
    public_symbols = [s for s in dir(logstats) if not s.startswith("_")]
    assert sorted(public_symbols) == ["analyze", "main", "parse_line"]
    assert logstats.__all__ == ["parse_line", "analyze", "main"]
