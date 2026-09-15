from datetime import timedelta

from logstats import analyze, main, parse_line

SAMPLE = (
    '203.0.113.10 - - [09/Sep/2026:08:00:01 +0800] "GET /api/users HTTP/1.1" 200 1024 0.042'
)
SAMPLE_USER = (
    '198.51.100.7 - alice [09/Sep/2026:08:00:03 +0800] "GET / HTTP/1.1" 304 - 0.011'
)


def test_parse_well_formed_fields():
    rec = parse_line(SAMPLE)
    assert rec is not None
    assert rec["ip"] == "203.0.113.10"
    assert rec["user"] is None
    assert rec["method"] == "GET"
    assert rec["path"] == "/api/users"
    assert rec["protocol"] == "HTTP/1.1"
    assert rec["status"] == 200
    assert rec["bytes"] == 1024
    assert rec["duration"] == 0.042
    assert rec["timestamp"].utcoffset() == timedelta(hours=8)


def test_parse_malformed_returns_none():
    assert parse_line("this line is not a log line at all") is None
    assert parse_line('10.0.0.5 - - [09/Sep/2026:08:00:53 BAD] "GET /admin HTTP/1.1" 403 64 0.005') is None


def test_parse_dash_bytes_is_zero():
    rec = parse_line(SAMPLE_USER)
    assert rec is not None
    assert rec["bytes"] == 0


def test_parse_dash_user_is_none_named_user_kept():
    rec = parse_line(SAMPLE)
    assert rec is not None
    assert rec["user"] is None
    rec2 = parse_line(SAMPLE_USER)
    assert rec2 is not None
    assert rec2["user"] == "alice"


def test_parse_tolerates_line_terminators():
    rec_n = parse_line(SAMPLE + "\n")
    rec_rn = parse_line(SAMPLE + "\r\n")
    assert rec_n is not None and rec_rn is not None
    assert rec_n["ip"] == rec_rn["ip"] == "203.0.113.10"


def test_percentile_nearest_rank():
    lines = [
        '1.1.1.1 - - [09/Sep/2026:08:00:01 +0800] "GET /a HTTP/1.1" 200 1 1.0',
        '1.1.1.1 - - [09/Sep/2026:08:00:02 +0800] "GET /a HTTP/1.1" 200 1 2.0',
        '1.1.1.1 - - [09/Sep/2026:08:00:03 +0800] "GET /a HTTP/1.1" 200 1 3.0',
        '1.1.1.1 - - [09/Sep/2026:08:00:04 +0800] "GET /a HTTP/1.1" 200 1 4.0',
    ]
    report = analyze(lines)
    assert report["duration"]["p50"] == 2.0
    assert report["duration"]["p95"] == 4.0
    assert report["status_classes"] == {
        "2xx": 4,
        "3xx": 0,
        "4xx": 0,
        "5xx": 0,
        "other": 0,
    }


def test_top_truncation_and_tie_break():
    lines = [
        '1.1.1.1 - - [09/Sep/2026:08:00:01 +0800] "GET /b HTTP/1.1" 200 1 0.1',
        '1.1.1.1 - - [09/Sep/2026:08:00:02 +0800] "GET /b HTTP/1.1" 200 1 0.1',
        '2.2.2.2 - - [09/Sep/2026:08:00:03 +0800] "GET /a HTTP/1.1" 200 1 0.1',
        '2.2.2.2 - - [09/Sep/2026:08:00:04 +0800] "GET /a HTTP/1.1" 200 1 0.1',
        '3.3.3.3 - - [09/Sep/2026:08:00:05 +0800] "GET /c HTTP/1.1" 200 1 0.1',
        '0.0.0.0 - - [09/Sep/2026:08:00:06 +0800] "GET /z HTTP/1.1" 101 1 0.1',
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
    assert report["status_classes"]["other"] == 1
    assert list(report["methods"]) == ["GET"]


def test_blank_lines_ignored_and_empty_duration():
    report = analyze(["  ", "\n", "\r\n", ""])
    assert report["lines_total"] == 0
    assert report["lines_parsed"] == 0
    assert report["lines_malformed"] == 0
    assert report["duration"] == {
        "count": 0,
        "mean": 0.0,
        "p50": 0.0,
        "p95": 0.0,
        "max": 0.0,
    }


def test_strict_exits_two(tmp_path, capsys):
    log = tmp_path / "access.log"
    log.write_text(
        SAMPLE + "\nnot a log line\n" + SAMPLE_USER + "\n",
        encoding="utf-8",
    )
    code = main([str(log), "--strict"])
    captured = capsys.readouterr()
    assert code == 2
    assert captured.out == ""
    assert captured.err == "malformed line 2: not a log line\n"


def test_missing_file_exits_two(tmp_path, capsys):
    missing = tmp_path / "no-such-file.log"
    code = main([str(missing)])
    captured = capsys.readouterr()
    assert code == 2
    assert captured.out == ""
    assert captured.err != ""


def test_cli_json_and_invalid_top(tmp_path, capsys):
    log = tmp_path / "ok.log"
    log.write_text(SAMPLE + "\n", encoding="utf-8")
    code = main([str(log), "--top", "1"])
    captured = capsys.readouterr()
    assert code == 0
    payload = captured.out
    assert payload.endswith("\n")
    assert '"lines_total": 1' in payload

    code = main([str(log), "--top", "0"])
    captured = capsys.readouterr()
    assert code == 2
    assert captured.out == ""
    assert captured.err != ""

    code = main([str(log), "--format", "table"])
    captured = capsys.readouterr()
    assert code == 0
    text = captured.out
    for needle in ("lines_total", "status_classes", "top_paths", "top_ips", "duration"):
        assert needle in text
    import json

    try:
        json.loads(text)
        raise AssertionError("table output must not be valid JSON")
    except json.JSONDecodeError:
        pass
