import json

import logstats


def _line(ip="1.1.1.1", path="/", duration="1.0", status="200", method="GET"):
    return (
        f'{ip} - - [09/Sep/2026:08:00:01 +0800] '
        f'"{method} {path} HTTP/1.1" {status} 10 {duration}'
    )


def test_parse_well_formed_line_field_by_field():
    record = logstats.parse_line(
        '203.0.113.10 - - [09/Sep/2026:08:00:01 +0800] '
        '"GET /api/users HTTP/1.1" 200 1024 0.042\n'
    )
    assert record["ip"] == "203.0.113.10"
    assert record["user"] is None
    assert record["method"] == "GET"
    assert record["path"] == "/api/users"
    assert record["protocol"] == "HTTP/1.1"
    assert record["status"] == 200
    assert record["bytes"] == 1024
    assert record["duration"] == 0.042
    assert record["timestamp"].utcoffset().total_seconds() == 8 * 3600


def test_parse_malformed_line_returns_none():
    assert logstats.parse_line("this line is not a log line at all") is None


def test_dash_bytes_become_zero():
    record = logstats.parse_line(_line().replace(" 10 1.0", " - 1.0"))
    assert record["bytes"] == 0


def test_dash_user_becomes_none_and_named_user_is_kept():
    assert logstats.parse_line(_line())["user"] is None
    named = logstats.parse_line(_line().replace(" - - [", " - alice ["))
    assert named["user"] == "alice"


def test_percentiles_use_nearest_rank():
    result = logstats.analyze([_line(duration=f"{value}.0") for value in (1, 2, 3, 4)])
    assert result["duration"]["p50"] == 2.0
    assert result["duration"]["p95"] == 4.0


def test_top_truncation_and_tie_breaking():
    lines = [_line(path="/b"), _line(path="/a"), _line(path="/c"), _line(path="/b")]
    result = logstats.analyze(lines, top=2)
    assert result["top_paths"] == [{"path": "/b", "count": 2}, {"path": "/a", "count": 1}]


def test_blank_lines_are_ignored_and_status_classes_are_complete():
    result = logstats.analyze(["  \n", _line(status="199"), _line(status="600")])
    assert result["lines_total"] == 2
    assert result["status_classes"] == {
        "2xx": 0, "3xx": 0, "4xx": 0, "5xx": 0, "other": 2
    }


def test_strict_cli_exits_two_without_stdout(tmp_path, capsys):
    logfile = tmp_path / "access.log"
    logfile.write_text(_line() + "\n" + "bad\n", encoding="utf-8")
    assert logstats.main([str(logfile), "--strict"]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "malformed line 2: bad" in captured.err


def test_missing_file_exits_two_without_stdout(capsys):
    assert logstats.main(["does-not-exist.log"]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err


def test_json_cli_output(tmp_path, capsys):
    logfile = tmp_path / "access.log"
    logfile.write_text(_line() + "\n", encoding="utf-8")
    assert logstats.main([str(logfile)]) == 0
    assert json.loads(capsys.readouterr().out)["lines_parsed"] == 1
