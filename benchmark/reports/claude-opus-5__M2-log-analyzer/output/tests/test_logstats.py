import json

import pytest

from logstats import analyze, main, parse_line

GOOD = (
    '203.0.113.10 - - [09/Sep/2026:08:00:01 +0800] '
    '"GET /api/users HTTP/1.1" 200 1024 0.042'
)


def _line(ip="1.1.1.1", user="-", sec=1, method="GET", path="/a", status=200,
          size=1, duration="0.5"):
    return (
        f'{ip} - {user} [09/Sep/2026:08:00:{sec:02d} +0800] '
        f'"{method} {path} HTTP/1.1" {status} {size} {duration}'
    )


def test_parse_well_formed_line_field_by_field():
    rec = parse_line(GOOD)
    assert rec == {
        "ip": "203.0.113.10",
        "user": None,
        "timestamp": rec["timestamp"],
        "method": "GET",
        "path": "/api/users",
        "protocol": "HTTP/1.1",
        "status": 200,
        "bytes": 1024,
        "duration": 0.042,
    }
    assert rec["timestamp"].utcoffset().total_seconds() == 8 * 3600
    assert (rec["timestamp"].year, rec["timestamp"].month, rec["timestamp"].day) == (
        2026, 9, 9,
    )


@pytest.mark.parametrize("bad", [
    "this line is not a log line at all",
    '"GET /orphan HTTP/1.1" 200 100 0.010',
    '10.0.0.5 - - [09/Sep/2026:08:00:53 BAD] "GET /admin HTTP/1.1" 403 64 0.005',
    '1.1.1.1 - - [09/Sep/2026:08:00:01 +0800] "GET /a HTTP/1.1" 200 1024 abc',
    '1.1.1.1 - - [09/Sep/2026:08:00:01 +0800] "get /a HTTP/1.1" 200 1024 0.1',
    '1.1.1.1 - - [09/Sep/2026:08:00:01 +0800] "GET /a HTTP/1.1" 20 1024 0.1',
])
def test_malformed_lines_return_none(bad):
    assert parse_line(bad) is None


def test_dash_bytes_and_named_user_and_line_terminators():
    raw = (
        '198.51.100.7 - alice [09/Sep/2026:08:00:03 +0800] '
        '"GET / HTTP/1.1" 304 - 0.011'
    )
    rec = parse_line(raw)
    assert rec["bytes"] == 0 and rec["user"] == "alice"
    assert parse_line(raw + "\n") == rec
    assert parse_line(raw + "\r\n") == rec


def test_percentiles_use_nearest_rank():
    report = analyze([_line(sec=i, duration=str(float(i))) for i in range(1, 5)])
    assert report["duration"] == {
        "count": 4, "mean": 2.5, "p50": 2.0, "p95": 4.0, "max": 4.0,
    }
    assert report["status_classes"] == {
        "2xx": 4, "3xx": 0, "4xx": 0, "5xx": 0, "other": 0,
    }
    single = analyze([_line(duration="0.25")])
    assert single["duration"]["p50"] == 0.25 and single["duration"]["p95"] == 0.25


def test_empty_and_blank_input():
    report = analyze(["", "   ", "\n", "\t\n"])
    assert report["lines_total"] == 0
    assert report["lines_malformed"] == 0
    assert report["duration"] == {
        "count": 0, "mean": 0.0, "p50": 0.0, "p95": 0.0, "max": 0.0,
    }
    assert list(report) == [
        "lines_total", "lines_parsed", "lines_malformed", "bytes_total",
        "status_classes", "methods", "top_paths", "top_ips", "duration",
    ]


def test_top_truncation_and_tie_breaking():
    lines = [
        _line(path="/b", ip="2.2.2.2"),
        _line(path="/b", ip="2.2.2.2"),
        _line(path="/a", ip="1.1.1.1"),
        _line(path="/c", ip="3.3.3.3"),
    ]
    report = analyze(lines, top=2)
    assert report["top_paths"] == [
        {"path": "/b", "count": 2}, {"path": "/a", "count": 1},
    ]
    assert report["top_ips"] == [
        {"ip": "2.2.2.2", "count": 2}, {"ip": "1.1.1.1", "count": 1},
    ]


def test_counts_bytes_methods_and_status_other():
    lines = [
        _line(method="POST", status=301, size="-"),
        _line(method="GET", status=404, size=10),
        _line(method="GET", status=599, size=5),
        _line(method="DELETE", status=100, size=1),
        "garbage",
        "",
    ]
    report = analyze(lines)
    assert report["lines_total"] == 5
    assert report["lines_parsed"] == 4
    assert report["lines_malformed"] == 1
    assert report["bytes_total"] == 16
    assert report["methods"] == {"DELETE": 1, "GET": 2, "POST": 1}
    assert report["status_classes"] == {
        "2xx": 0, "3xx": 1, "4xx": 1, "5xx": 1, "other": 1,
    }


def test_cli_json_output(tmp_path, capsys):
    log = tmp_path / "a.log"
    log.write_text(_line() + "\n" + "junk\n", encoding="utf-8")
    assert main([str(log)]) == 0
    out = capsys.readouterr()
    assert out.err == ""
    assert out.out.endswith("\n")
    report = json.loads(out.out)
    assert report["lines_total"] == 2 and report["lines_malformed"] == 1


def test_cli_table_output(tmp_path, capsys):
    log = tmp_path / "a.log"
    log.write_text(_line() + "\n", encoding="utf-8")
    assert main([str(log), "--format", "table"]) == 0
    out = capsys.readouterr().out
    for token in ("lines_total", "status_classes", "top_paths", "top_ips", "duration"):
        assert token in out
    with pytest.raises(ValueError):
        json.loads(out)


def test_cli_strict_exits_two(tmp_path, capsys):
    log = tmp_path / "a.log"
    log.write_text(_line() + "\n\nbroken line\n" + _line() + "\n", encoding="utf-8")
    assert main([str(log), "--strict"]) == 2
    out = capsys.readouterr()
    assert out.out == ""
    assert out.err.strip() == "malformed line 3: broken line"


def test_cli_missing_file_exits_two(tmp_path, capsys):
    assert main([str(tmp_path / "nope.log")]) == 2
    out = capsys.readouterr()
    assert out.out == ""
    assert out.err != ""


@pytest.mark.parametrize("top", ["0", "-3", "abc"])
def test_cli_bad_top_exits_two(tmp_path, capsys, top):
    log = tmp_path / "a.log"
    log.write_text(_line() + "\n", encoding="utf-8")
    assert main([str(log), "--top", top]) == 2
    out = capsys.readouterr()
    assert out.out == ""
    assert out.err != ""
