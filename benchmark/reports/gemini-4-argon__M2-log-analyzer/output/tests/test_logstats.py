from datetime import datetime, timedelta, timezone
import json
import pytest

import logstats
from logstats import analyze, main, parse_line


def test_parse_line_well_formed_and_newlines():
    raw = '203.0.113.10 - - [09/Sep/2026:08:00:01 +0800] "GET /api/users HTTP/1.1" 200 1024 0.042'
    for suffix in ("", "\n", "\r\n"):
        rec = parse_line(raw + suffix)
        assert rec is not None
        assert list(rec.keys()) == [
            "ip",
            "user",
            "timestamp",
            "method",
            "path",
            "protocol",
            "status",
            "bytes",
            "duration",
        ]
        assert rec["ip"] == "203.0.113.10"
        assert rec["user"] is None
        assert rec["timestamp"] == datetime(
            2026, 9, 9, 8, 0, 1, tzinfo=timezone(timedelta(hours=8))
        )
        assert rec["timestamp"].utcoffset().total_seconds() == 8 * 3600
        assert rec["method"] == "GET"
        assert rec["path"] == "/api/users"
        assert rec["protocol"] == "HTTP/1.1"
        assert rec["status"] == 200
        assert rec["bytes"] == 1024
        assert rec["duration"] == 0.042


def test_parse_line_malformed():
    malformed_samples = [
        "",
        "   \n",
        "this line is not a log line at all",
        '999.0.113.10 - - [09/Sep/2026:08:00:01 +0800] "GET / HTTP/1.1" 200 10 0.01',
        '10.0.0.5 - - [09/Sep/2026:08:00:53 BAD] "GET /admin HTTP/1.1" 403 64 0.005',
        '"GET /orphan HTTP/1.1" 200 100 0.010',
        '192.0.2.44 - - [09/Sep/2026:08:01:15 +0800] "GET /api/users HTTP/1.1" 200 1024 abc',
        '192.0.2.44 - - [09/Sep/2026:08:01:15 +0800] "get /api/users HTTP/1.1" 200 1024 0.01',
        '192.0.2.44 - - [31/Feb/2026:08:01:15 +0800] "GET /api/users HTTP/1.1" 200 1024 0.01',
    ]
    for sample in malformed_samples:
        assert parse_line(sample) is None


def test_parse_line_dash_bytes_and_named_user():
    rec = parse_line(
        '198.51.100.7 - alice [09/Sep/2026:08:00:03 +0800] "GET / HTTP/1.1" 304 - 0.011'
    )
    assert rec is not None
    assert rec["bytes"] == 0
    assert rec["user"] == "alice"


def test_analyze_percentile_and_status_classes():
    lines = [
        '1.1.1.1 - - [09/Sep/2026:08:00:01 +0800] "GET /a HTTP/1.1" 200 1 1.0',
        '1.1.1.1 - - [09/Sep/2026:08:00:02 +0800] "GET /a HTTP/1.1" 200 1 2.0',
        '1.1.1.1 - - [09/Sep/2026:08:00:03 +0800] "GET /a HTTP/1.1" 200 1 3.0',
        '1.1.1.1 - - [09/Sep/2026:08:00:04 +0800] "GET /a HTTP/1.1" 200 1 4.0',
    ]
    report = analyze(lines)
    assert report["duration"] == {
        "count": 4,
        "mean": 2.5,
        "p50": 2.0,
        "p95": 4.0,
        "max": 4.0,
    }
    assert report["status_classes"] == {
        "2xx": 4,
        "3xx": 0,
        "4xx": 0,
        "5xx": 0,
        "other": 0,
    }


def test_analyze_top_truncation_and_tie_breaking():
    lines = [
        '10.0.0.2 - - [09/Sep/2026:08:00:01 +0800] "GET /b HTTP/1.1" 200 10 0.1',
        '10.0.0.2 - - [09/Sep/2026:08:00:02 +0800] "GET /b HTTP/1.1" 200 10 0.1',
        '10.0.0.1 - - [09/Sep/2026:08:00:03 +0800] "POST /a HTTP/1.1" 101 10 0.1',
        '10.0.0.1 - - [09/Sep/2026:08:00:04 +0800] "POST /a HTTP/1.1" 500 10 0.1',
        '10.0.0.3 - - [09/Sep/2026:08:00:05 +0800] "DELETE /c HTTP/1.1" 404 10 0.1',
        "",
        "   \t  \n",
        "malformed line here",
    ]
    report = analyze(lines, top=2)
    assert report["lines_total"] == 6
    assert report["lines_parsed"] == 5
    assert report["lines_malformed"] == 1
    assert report["bytes_total"] == 50
    assert report["top_paths"] == [
        {"path": "/a", "count": 2},
        {"path": "/b", "count": 2},
    ]
    assert report["top_ips"] == [
        {"ip": "10.0.0.1", "count": 2},
        {"ip": "10.0.0.2", "count": 2},
    ]
    assert list(report["methods"].keys()) == ["DELETE", "GET", "POST"]
    assert report["status_classes"]["other"] == 1


def test_analyze_empty_and_all_malformed():
    report = analyze(["", "   \n", "bad line 1", "bad line 2"])
    assert report["lines_total"] == 2
    assert report["lines_parsed"] == 0
    assert report["lines_malformed"] == 2
    assert report["bytes_total"] == 0
    assert report["methods"] == {}
    assert report["top_paths"] == []
    assert report["top_ips"] == []
    assert report["duration"] == {
        "count": 0,
        "mean": 0.0,
        "p50": 0.0,
        "p95": 0.0,
        "max": 0.0,
    }


def test_cli_strict_exits_2_on_first_malformed_line(tmp_path, capsys):
    log_file = tmp_path / "sample.log"
    log_file.write_text(
        '1.1.1.1 - - [09/Sep/2026:08:00:01 +0800] "GET / HTTP/1.1" 200 10 0.01\n'
        "\n"
        "bad line one\n"
        "bad line two\n",
        encoding="utf-8",
    )
    rc = main([str(log_file), "--strict"])
    captured = capsys.readouterr()
    assert rc == 2
    assert captured.out == ""
    assert captured.err.strip() == "malformed line 3: bad line one"


def test_cli_missing_file_and_invalid_top_exit_2(tmp_path, capsys):
    missing = tmp_path / "does_not_exist.log"
    rc = main([str(missing)])
    captured = capsys.readouterr()
    assert rc == 2
    assert captured.out == ""
    assert captured.err != ""

    valid_file = tmp_path / "valid.log"
    valid_file.write_text(
        '1.1.1.1 - - [09/Sep/2026:08:00:01 +0800] "GET / HTTP/1.1" 200 10 0.01\n',
        encoding="utf-8",
    )
    for bad_top in ("0", "-3", "abc"):
        rc_top = main([str(valid_file), "--top", bad_top])
        cap_top = capsys.readouterr()
        assert rc_top == 2
        assert cap_top.out == ""
        assert cap_top.err != ""


def test_cli_json_and_table_formats_and_public_api(tmp_path, capsys):
    log_file = tmp_path / "ok.log"
    log_file.write_text(
        '1.1.1.1 - - [09/Sep/2026:08:00:01 +0800] "GET /x HTTP/1.1" 200 100 0.123\n'
        "not a valid line\n",
        encoding="utf-8",
    )
    rc_json = main([str(log_file), "--top", "3", "--format", "json"])
    cap_json = capsys.readouterr()
    assert rc_json == 0
    assert cap_json.err == ""
    parsed_json = json.loads(cap_json.out)
    assert parsed_json["lines_total"] == 2
    assert parsed_json["lines_parsed"] == 1
    assert parsed_json["lines_malformed"] == 1

    rc_table = main([str(log_file), "--format", "table"])
    cap_table = capsys.readouterr()
    assert rc_table == 0
    for required_token in ("lines_total", "status_classes", "top_paths", "top_ips", "duration"):
        assert required_token in cap_table.out
    with pytest.raises(json.JSONDecodeError):
        json.loads(cap_table.out)

    public_names = sorted(name for name in dir(logstats) if not name.startswith("_"))
    assert public_names == ["analyze", "main", "parse_line"]
