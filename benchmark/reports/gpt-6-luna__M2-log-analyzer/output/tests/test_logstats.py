import json
from datetime import datetime, timedelta

import pytest

import logstats


def _line(
    *,
    ip="203.0.113.10",
    user="-",
    timestamp="09/Sep/2026:08:00:01 +0800",
    method="GET",
    path="/api/users",
    status=200,
    size="1024",
    duration="0.042",
):
    return (
        f'{ip} - {user} [{timestamp}] "{method} {path} HTTP/1.1" '
        f"{status} {size} {duration}"
    )


def test_parse_well_formed_line_field_by_field():
    record = logstats.parse_line(_line())

    assert record is not None
    assert set(record) == {
        "ip", "user", "timestamp", "method", "path", "protocol",
        "status", "bytes", "duration",
    }
    assert record["ip"] == "203.0.113.10"
    assert record["user"] is None
    assert record["method"] == "GET"
    assert record["path"] == "/api/users"
    assert record["protocol"] == "HTTP/1.1"
    assert record["status"] == 200
    assert record["bytes"] == 1024
    assert record["duration"] == 0.042
    assert isinstance(record["timestamp"], datetime)
    assert record["timestamp"].utcoffset() == timedelta(hours=8)


def test_parse_tolerates_line_terminators():
    assert logstats.parse_line(_line() + "\n") is not None
    assert logstats.parse_line(_line() + "\r\n") is not None


def test_malformed_line_returns_none():
    assert logstats.parse_line("this line is not a log line at all") is None


def test_dash_values_are_converted():
    record = logstats.parse_line(_line(ip="198.51.100.7", user="alice", path="/", status=304, size="-"))

    assert record is not None
    assert record["bytes"] == 0
    assert record["user"] == "alice"


def test_analyze_ignores_blank_lines_and_counts_malformed():
    report = logstats.analyze(["", " \t\r\n", _line(), "broken\n"])

    assert report["lines_total"] == 2
    assert report["lines_parsed"] == 1
    assert report["lines_malformed"] == 1


def test_nearest_rank_percentiles_and_status_classes():
    lines = [
        _line(timestamp=f"09/Sep/2026:08:00:0{n} +0800", duration=f"{n}.0")
        for n in range(1, 5)
    ]
    report = logstats.analyze(lines)

    assert report["duration"]["p50"] == 2.0
    assert report["duration"]["p95"] == 4.0
    assert report["status_classes"] == {
        "2xx": 4, "3xx": 0, "4xx": 0, "5xx": 0, "other": 0,
    }


def test_top_truncation_and_tie_breaking():
    lines = [
        _line(ip="203.0.113.2", path="/b"),
        _line(ip="203.0.113.1", path="/a"),
        _line(ip="203.0.113.1", path="/b"),
        _line(ip="203.0.113.3", path="/c"),
    ]
    report = logstats.analyze(lines, top=2)

    assert report["top_paths"] == [
        {"path": "/b", "count": 2},
        {"path": "/a", "count": 1},
    ]
    assert report["top_ips"] == [
        {"ip": "203.0.113.1", "count": 2},
        {"ip": "203.0.113.2", "count": 1},
    ]


def test_status_other_and_empty_duration_defaults():
    report = logstats.analyze(["invalid", _line(status=199)])

    assert report["status_classes"]["other"] == 1
    assert report["duration"] == {
        "count": 1, "mean": 0.042, "p50": 0.042, "p95": 0.042, "max": 0.042,
    }
    empty = logstats.analyze(["", "bad"])
    assert empty["duration"] == {
        "count": 0, "mean": 0.0, "p50": 0.0, "p95": 0.0, "max": 0.0,
    }


def test_strict_mode_stops_without_stdout(tmp_path, capsys):
    logfile = tmp_path / "sample.log"
    logfile.write_text(_line() + "\nmalformed record\n", encoding="utf-8")

    assert logstats.main([str(logfile), "--strict"]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "malformed line 2: malformed record\n"


def test_missing_file_returns_two_without_stdout(tmp_path, capsys):
    assert logstats.main([str(tmp_path / "missing.log")]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "cannot read" in captured.err


def test_cli_json_and_table_formats(tmp_path, capsys):
    logfile = tmp_path / "sample.log"
    logfile.write_text(_line() + "\n", encoding="utf-8")

    assert logstats.main([str(logfile)]) == 0
    assert json.loads(capsys.readouterr().out)["lines_parsed"] == 1
    assert logstats.main([str(logfile), "--format", "table"]) == 0
    output = capsys.readouterr().out
    assert all(key in output for key in ("lines_total", "status_classes", "top_paths", "top_ips", "duration"))
    with pytest.raises(json.JSONDecodeError):
        json.loads(output)


@pytest.mark.parametrize("top", ["0", "not-a-number"])
def test_invalid_top_is_usage_error(top, tmp_path, capsys):
    assert logstats.main([str(tmp_path / "unused"), "--top", top]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err
