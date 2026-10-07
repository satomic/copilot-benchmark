import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import logstats
from logstats import analyze, main, parse_line

GOOD = '203.0.113.10 - - [09/Sep/2026:08:00:01 +0800] "GET /api/users HTTP/1.1" 200 1024 0.042'


def _line(ip="1.1.1.1", path="/a", status=200, dur="1.0", method="GET"):
    return f'{ip} - - [09/Sep/2026:08:00:01 +0800] "{method} {path} HTTP/1.1" {status} 1 {dur}'


def test_parse_fields():
    rec = parse_line(GOOD)
    assert rec["ip"] == "203.0.113.10"
    assert rec["user"] is None
    assert rec["method"] == "GET" and rec["path"] == "/api/users"
    assert rec["protocol"] == "HTTP/1.1"
    assert rec["status"] == 200 and rec["bytes"] == 1024
    assert rec["duration"] == 0.042
    assert rec["timestamp"].utcoffset().total_seconds() == 8 * 3600


def test_malformed_none():
    assert parse_line("this line is not a log line at all") is None
    assert parse_line(GOOD.replace("0.042", "abc")) is None
    assert parse_line(GOOD.replace("+0800", "BAD")) is None


def test_dash_bytes_and_user():
    rec = parse_line('198.51.100.7 - alice [09/Sep/2026:08:00:03 +0800] "GET / HTTP/1.1" 304 - 0.011')
    assert rec["bytes"] == 0 and rec["user"] == "alice"


def test_trailing_newlines():
    assert parse_line(GOOD + "\n") == parse_line(GOOD)
    assert parse_line(GOOD + "\r\n") == parse_line(GOOD)


def test_percentiles():
    r = analyze([_line(dur=str(d)) for d in (1.0, 2.0, 3.0, 4.0)])
    assert r["duration"]["p50"] == 2.0
    assert r["duration"]["p95"] == 4.0
    assert r["duration"]["max"] == 4.0
    assert r["duration"]["mean"] == 2.5
    assert r["status_classes"] == {"2xx": 4, "3xx": 0, "4xx": 0, "5xx": 0, "other": 0}


def test_top_truncation_and_ties():
    lines = [_line(path="/b")] * 2 + [_line(path="/a")] * 2 + [_line(path="/c")] * 3 + [_line(path="/d")]
    r = analyze(lines, top=3)
    assert r["top_paths"] == [
        {"path": "/c", "count": 3},
        {"path": "/a", "count": 2},
        {"path": "/b", "count": 2},
    ]


def test_blank_and_empty_and_status_other():
    r = analyze(["", "  \n", _line(status=101), _line(status=600), "junk"])
    assert r["lines_total"] == 3 and r["lines_parsed"] == 2 and r["lines_malformed"] == 1
    assert r["status_classes"]["other"] == 2
    e = analyze([])
    assert e["duration"] == {"count": 0, "mean": 0.0, "p50": 0.0, "p95": 0.0, "max": 0.0}
    assert list(e) == ["lines_total", "lines_parsed", "lines_malformed", "bytes_total",
                       "status_classes", "methods", "top_paths", "top_ips", "duration"]


def test_strict_exit_2(tmp_path, capsys):
    f = tmp_path / "a.log"
    f.write_text(GOOD + "\n\nbroken line\n" + GOOD + "\n")
    assert main([str(f), "--strict"]) == 2
    cap = capsys.readouterr()
    assert cap.out == ""
    assert "malformed line 3: broken line" in cap.err


def test_missing_file(tmp_path, capsys):
    assert main([str(tmp_path / "nope.log")]) == 2
    cap = capsys.readouterr()
    assert cap.out == "" and cap.err


def test_bad_top(tmp_path, capsys):
    f = tmp_path / "a.log"
    f.write_text(GOOD + "\n")
    for bad in ("0", "-1", "x"):
        assert main([str(f), "--top", bad]) == 2
        assert capsys.readouterr().out == ""


def test_cli_json_and_table(tmp_path, capsys):
    f = tmp_path / "a.log"
    f.write_text(GOOD + "\nbroken\n")
    assert main([str(f)]) == 0
    out = capsys.readouterr().out
    assert out.endswith("}\n")
    assert json.loads(out)["lines_malformed"] == 1
    assert main([str(f), "--format", "table"]) == 0
    out = capsys.readouterr().out
    for s in ("lines_total", "status_classes", "top_paths", "top_ips", "duration"):
        assert s in out
    try:
        json.loads(out)
        assert False, "table output must not be JSON"
    except ValueError:
        pass


def test_public_api_only():
    public = {n for n in dir(logstats) if not n.startswith("_")}
    assert public == {"parse_line", "analyze", "main"}
