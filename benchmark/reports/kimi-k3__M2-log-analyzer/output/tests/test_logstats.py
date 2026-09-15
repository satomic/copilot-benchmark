"""Tests for logstats.py — fixtures are inline; access.log is never touched."""

import datetime
import json
import sys

import pytest

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))

import logstats

GOOD_LINE = (
    '203.0.113.10 - - [09/Sep/2026:08:00:01 +0800] '
    '"GET /api/users HTTP/1.1" 200 1024 0.042'
)


def _line(ip="1.1.1.1", user="-", ts="09/Sep/2026:08:00:01 +0800",
          method="GET", path="/a", protocol="HTTP/1.1", status="200",
          bytes_="1", duration="1.0"):
    return (f'{ip} - {user} [{ts}] "{method} {path} {protocol}" '
            f'{status} {bytes_} {duration}')


def test_parse_well_formed_field_by_field():
    rec = logstats.parse_line(GOOD_LINE)
    assert rec is not None
    assert rec["ip"] == "203.0.113.10"
    assert rec["user"] is None
    assert rec["method"] == "GET"
    assert rec["path"] == "/api/users"
    assert rec["protocol"] == "HTTP/1.1"
    assert rec["status"] == 200
    assert rec["bytes"] == 1024
    assert rec["duration"] == 0.042
    assert isinstance(rec["timestamp"], datetime.datetime)
    assert rec["timestamp"].utcoffset().total_seconds() == 8 * 3600


def test_parse_malformed_returns_none():
    assert logstats.parse_line("this line is not a log line at all") is None
    assert logstats.parse_line("") is None
    assert logstats.parse_line(_line(duration="abc")) is None
    assert logstats.parse_line(_line(ts="08:00:53 BAD")) is None


def test_parse_tolerates_trailing_newline():
    assert logstats.parse_line(GOOD_LINE + "\n") is not None
    assert logstats.parse_line(GOOD_LINE + "\r\n") is not None


def test_bytes_dash_becomes_zero_and_user_kept():
    rec = logstats.parse_line(_line(ip="198.51.100.7", user="alice",
                                    status="304", bytes_="-", duration="0.011"))
    assert rec["bytes"] == 0
    assert rec["user"] == "alice"
    rec2 = logstats.parse_line(_line(user="-"))
    assert rec2["user"] is None


def test_percentile_nearest_rank():
    report = logstats.analyze([
        _line(ts="09/Sep/2026:08:00:01 +0800", duration="1.0"),
        _line(ts="09/Sep/2026:08:00:02 +0800", duration="2.0"),
        _line(ts="09/Sep/2026:08:00:03 +0800", duration="3.0"),
        _line(ts="09/Sep/2026:08:00:04 +0800", duration="4.0"),
    ])
    assert report["duration"]["count"] == 4
    assert report["duration"]["p50"] == 2.0
    assert report["duration"]["p95"] == 4.0
    assert report["duration"]["max"] == 4.0
    assert report["duration"]["mean"] == 2.5
    assert report["status_classes"] == {
        "2xx": 4, "3xx": 0, "4xx": 0, "5xx": 0, "other": 0}


def test_analyze_counts_and_blank_lines():
    report = logstats.analyze([
        _line(),
        "",
        "   ",
        "garbage line",
        _line(bytes_="-", duration="0.5"),
    ])
    assert report["lines_total"] == 3
    assert report["lines_parsed"] == 2
    assert report["lines_malformed"] == 1
    assert report["bytes_total"] == 1
    assert report["methods"] == {"GET": 2}


def test_status_classes_buckets():
    report = logstats.analyze([
        _line(status="199"), _line(status="204"), _line(status="301"),
        _line(status="404"), _line(status="503"), _line(status="600"),
    ])
    assert report["status_classes"] == {
        "2xx": 1, "3xx": 1, "4xx": 1, "5xx": 1, "other": 2}


def test_empty_input_duration_defaults():
    report = logstats.analyze([])
    assert report["duration"] == {
        "count": 0, "mean": 0.0, "p50": 0.0, "p95": 0.0, "max": 0.0}
    assert report["lines_total"] == 0


def test_top_truncation_and_tie_breaking():
    lines = (
        [_line(ip="10.0.0.2", path="/b")] * 2
        + [_line(ip="10.0.0.1", path="/a")] * 2
        + [_line(ip="10.0.0.3", path="/c")]
    )
    report = logstats.analyze(lines, top=2)
    assert report["top_paths"] == [
        {"path": "/a", "count": 2}, {"path": "/b", "count": 2}]
    assert report["top_ips"] == [
        {"ip": "10.0.0.1", "count": 2}, {"ip": "10.0.0.2", "count": 2}]
    assert len(report["top_paths"]) == 2


def test_report_key_order():
    report = logstats.analyze([_line()])
    assert list(report.keys()) == [
        "lines_total", "lines_parsed", "lines_malformed", "bytes_total",
        "status_classes", "methods", "top_paths", "top_ips", "duration"]
    assert list(report["status_classes"].keys()) == [
        "2xx", "3xx", "4xx", "5xx", "other"]
    assert list(report["duration"].keys()) == [
        "count", "mean", "p50", "p95", "max"]


def test_cli_json_output(tmp_path, capsys):
    log = tmp_path / "test.log"
    log.write_text(GOOD_LINE + "\n" + "bad line\n", encoding="utf-8")
    code = logstats.main([str(log)])
    assert code == 0
    out = capsys.readouterr().out
    assert out.endswith("\n")
    report = json.loads(out)
    assert report["lines_total"] == 2
    assert report["lines_parsed"] == 1
    assert report["lines_malformed"] == 1


def test_cli_strict_exits_2(tmp_path, capsys):
    log = tmp_path / "test.log"
    log.write_text(GOOD_LINE + "\n" + "not a log line\n" + GOOD_LINE + "\n",
                   encoding="utf-8")
    code = logstats.main([str(log), "--strict"])
    assert code == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "malformed line 2: not a log line" in captured.err


def test_cli_missing_file_exits_2(capsys):
    code = logstats.main(["no_such_file.log"])
    assert code == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err != ""


def test_cli_bad_top_exits_2(tmp_path, capsys):
    log = tmp_path / "test.log"
    log.write_text(GOOD_LINE + "\n", encoding="utf-8")
    for bad in ("0", "-3", "abc"):
        assert logstats.main([str(log), "--top", bad]) == 2
        captured = capsys.readouterr()
        assert captured.out == ""
        assert captured.err != ""


def test_cli_table_format(tmp_path, capsys):
    log = tmp_path / "test.log"
    log.write_text(GOOD_LINE + "\n", encoding="utf-8")
    code = logstats.main([str(log), "--format", "table"])
    assert code == 0
    out = capsys.readouterr().out
    for token in ("lines_total", "status_classes", "top_paths",
                  "top_ips", "duration"):
        assert token in out
    with pytest.raises(json.JSONDecodeError):
        json.loads(out)


def test_cli_top_option(tmp_path, capsys):
    lines = "\n".join(_line(path=f"/p{i}") for i in range(7)) + "\n"
    log = tmp_path / "test.log"
    log.write_text(lines, encoding="utf-8")
    assert logstats.main([str(log), "--top", "3"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert len(report["top_paths"]) == 3


def test_import_has_no_side_effects(capsys):
    import importlib
    importlib.reload(logstats)
    captured = capsys.readouterr()
    assert captured.out == "" and captured.err == ""
