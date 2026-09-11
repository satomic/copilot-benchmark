import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import logstats  # noqa: E402
from logstats import analyze, main, parse_line  # noqa: E402

GOOD = '203.0.113.10 - - [09/Sep/2026:08:00:01 +0800] "GET /api/users HTTP/1.1" 200 1024 0.042'
BAD = "this line is not a log line at all"


def _line(ip="1.1.1.1", path="/a", method="GET", status=200, duration=1.0, sec=1):
    return f'{ip} - - [09/Sep/2026:08:00:{sec:02d} +0800] "{method} {path} HTTP/1.1" {status} 1 {duration}'


def test_parse_well_formed_line_fields():
    rec = parse_line(GOOD)
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


def test_parse_tolerates_trailing_newline():
    assert parse_line(GOOD + "\n") == parse_line(GOOD)
    assert parse_line(GOOD + "\r\n") == parse_line(GOOD)


def test_parse_malformed_returns_none():
    assert parse_line(BAD) is None
    assert parse_line('10.0.0.5 - - [09/Sep/2026:08:00:53 BAD] "GET /admin HTTP/1.1" 403 64 0.005') is None
    assert parse_line('1.1.1.1 - - [09/Sep/2026:08:01:15 +0800] "GET /x HTTP/1.1" 200 1024 abc') is None
    assert parse_line(GOOD + " extra") is None


def test_dash_bytes_becomes_zero_and_named_user_kept():
    rec = parse_line('198.51.100.7 - alice [09/Sep/2026:08:00:03 +0800] "GET / HTTP/1.1" 304 - 0.011')
    assert rec["bytes"] == 0
    assert rec["user"] == "alice"


def test_dash_user_becomes_none():
    assert parse_line(GOOD)["user"] is None


def test_percentile_nearest_rank():
    r = analyze([_line(duration=d, sec=i) for i, d in enumerate([1.0, 2.0, 3.0, 4.0], 1)])
    assert r["duration"] == {"count": 4, "mean": 2.5, "p50": 2.0, "p95": 4.0, "max": 4.0}
    assert r["status_classes"] == {"2xx": 4, "3xx": 0, "4xx": 0, "5xx": 0, "other": 0}


def test_analyze_counts_blank_and_malformed_lines():
    r = analyze(["", "   \n", GOOD + "\n", BAD, '1.1.1.1 - - [x] "GET / HTTP/1.1" 999 5 0.1'])
    assert r["lines_total"] == 3
    assert r["lines_parsed"] == 1
    assert r["lines_malformed"] == 2
    assert r["bytes_total"] == 1024
    assert r["methods"] == {"GET": 1}


def test_status_other_class_and_method_sorting():
    r = analyze([
        _line(status=199, method="POST"),
        _line(status=600, method="DELETE"),
        _line(status=302, method="GET"),
        _line(status=404, method="GET"),
        _line(status=503, method="HEAD"),
    ])
    assert r["status_classes"] == {"2xx": 0, "3xx": 1, "4xx": 1, "5xx": 1, "other": 2}
    assert list(r["methods"]) == ["DELETE", "GET", "HEAD", "POST"]


def test_top_truncation_and_tie_breaking():
    lines = (
        [_line(path="/b", ip="2.2.2.2")] * 3
        + [_line(path="/a", ip="3.3.3.3")] * 3
        + [_line(path="/c", ip="1.1.1.1")] * 2
        + [_line(path="/d", ip="4.4.4.4")]
    )
    r = analyze(lines, top=2)
    assert r["top_paths"] == [{"path": "/a", "count": 3}, {"path": "/b", "count": 3}]
    assert r["top_ips"] == [{"ip": "2.2.2.2", "count": 3}, {"ip": "3.3.3.3", "count": 3}]
    assert len(analyze(lines, top=10)["top_paths"]) == 4


def test_empty_input_report():
    r = analyze([])
    assert r["duration"] == {"count": 0, "mean": 0.0, "p50": 0.0, "p95": 0.0, "max": 0.0}
    assert r["top_paths"] == [] and r["top_ips"] == [] and r["methods"] == {}
    assert list(r) == [
        "lines_total", "lines_parsed", "lines_malformed", "bytes_total",
        "status_classes", "methods", "top_paths", "top_ips", "duration",
    ]


def test_cli_json_output(tmp_path, capsys):
    log = tmp_path / "a.log"
    log.write_text(GOOD + "\n" + BAD + "\n\n" + GOOD + "\n")
    assert main([str(log), "--top", "1"]) == 0
    out, err = capsys.readouterr()
    assert err == ""
    assert out.endswith("\n") and not out.endswith("\n\n")
    report = json.loads(out)
    assert report["lines_total"] == 3
    assert report["lines_malformed"] == 1
    assert report["top_paths"] == [{"path": "/api/users", "count": 2}]
    assert out == json.dumps(report, indent=2) + "\n"


def test_cli_table_output(tmp_path, capsys):
    log = tmp_path / "a.log"
    log.write_text(GOOD + "\n")
    assert main([str(log), "--format", "table"]) == 0
    out, _ = capsys.readouterr()
    for token in ("lines_total", "status_classes", "top_paths", "top_ips", "duration"):
        assert token in out
    with pytest.raises(ValueError):
        json.loads(out)


def test_cli_strict_exits_2_on_first_malformed(tmp_path, capsys):
    log = tmp_path / "a.log"
    log.write_text(GOOD + "\n\n" + BAD + "\r\n" + "another bad\n")
    assert main([str(log), "--strict"]) == 2
    out, err = capsys.readouterr()
    assert out == ""
    assert err == f"malformed line 3: {BAD}\n"


def test_cli_strict_passes_clean_file(tmp_path, capsys):
    log = tmp_path / "a.log"
    log.write_text(GOOD + "\n")
    assert main([str(log), "--strict"]) == 0
    assert json.loads(capsys.readouterr().out)["lines_parsed"] == 1


def test_cli_missing_file_exits_2(tmp_path, capsys):
    assert main([str(tmp_path / "nope.log")]) == 2
    out, err = capsys.readouterr()
    assert out == ""
    assert err != ""


@pytest.mark.parametrize("top", ["0", "-3", "abc", "1.5"])
def test_cli_invalid_top_exits_2(tmp_path, capsys, top):
    log = tmp_path / "a.log"
    log.write_text(GOOD + "\n")
    assert main([str(log), "--top", top]) == 2
    out, err = capsys.readouterr()
    assert out == ""
    assert err != ""


def test_public_api_surface():
    public = [n for n in dir(logstats) if not n.startswith("_") and callable(getattr(logstats, n))]
    assert set(public) == {"parse_line", "analyze", "main"}
