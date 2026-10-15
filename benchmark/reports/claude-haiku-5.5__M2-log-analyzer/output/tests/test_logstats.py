import datetime as dt
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import logstats  # noqa: E402

GOOD = '203.0.113.10 - - [09/Sep/2026:08:00:01 +0800] "GET /api/users HTTP/1.1" 200 1024 0.042'


def _line(ts_status_bytes_dur="200 1 1.0", path="/a", ip="1.1.1.1", method="GET"):
    status, nbytes, dur = ts_status_bytes_dur.split()
    return (f'{ip} - - [09/Sep/2026:08:00:01 +0800] "{method} {path} HTTP/1.1" '
            f"{status} {nbytes} {dur}")


def test_parse_wellformed_line_fields():
    rec = logstats.parse_line(GOOD)
    assert rec["ip"] == "203.0.113.10"
    assert rec["user"] is None
    assert rec["method"] == "GET" and rec["path"] == "/api/users"
    assert rec["protocol"] == "HTTP/1.1"
    assert rec["status"] == 200 and rec["bytes"] == 1024
    assert rec["duration"] == 0.042
    assert rec["timestamp"] == dt.datetime(2026, 9, 9, 8, 0, 1, tzinfo=dt.timezone(dt.timedelta(hours=8)))
    assert rec["timestamp"].utcoffset().total_seconds() == 8 * 3600
    assert set(rec) == {"ip", "user", "timestamp", "method", "path",
                        "protocol", "status", "bytes", "duration"}


def test_parse_line_accepts_trailing_newlines():
    assert logstats.parse_line(GOOD + "\n") == logstats.parse_line(GOOD)
    assert logstats.parse_line(GOOD + "\r\n") == logstats.parse_line(GOOD)


def test_malformed_line_returns_none():
    assert logstats.parse_line("this line is not a log line at all") is None
    assert logstats.parse_line(GOOD.replace("0.042", "abc")) is None
    assert logstats.parse_line(GOOD.replace("+0800", "BAD")) is None
    assert logstats.parse_line(GOOD.replace("09/Sep", "31/Feb")) is None
    assert logstats.parse_line(GOOD.replace("203.0.113.10", "203.0.113.999")) is None


def test_bytes_dash_becomes_zero_and_named_user_kept():
    rec = logstats.parse_line(
        '198.51.100.7 - alice [09/Sep/2026:08:00:03 +0800] "GET / HTTP/1.1" 304 - 0.011'
    )
    assert rec["bytes"] == 0
    assert rec["user"] == "alice"
    assert rec["status"] == 304


def test_nearest_rank_percentile():
    report = logstats.analyze([_line(f"200 1 {d}.0") for d in (1, 2, 3, 4)])
    assert report["duration"]["p50"] == 2.0
    assert report["duration"]["p95"] == 4.0
    assert report["duration"]["max"] == 4.0
    assert report["duration"]["mean"] == 2.5
    assert report["duration"]["count"] == 4


def test_report_keys_order_and_status_classes():
    report = logstats.analyze([
        _line("200 1 1.0"), _line("301 1 1.0"), _line("404 1 1.0"),
        _line("503 1 1.0"), _line("999 1 1.0"), _line("100 1 1.0"),
    ])
    assert list(report) == [
        "lines_total", "lines_parsed", "lines_malformed", "bytes_total",
        "status_classes", "methods", "top_paths", "top_ips", "duration",
    ]
    assert report["status_classes"] == {"2xx": 1, "3xx": 1, "4xx": 1, "5xx": 1, "other": 2}


def test_empty_input_report():
    report = logstats.analyze([])
    assert report["lines_total"] == 0
    assert report["status_classes"] == {"2xx": 0, "3xx": 0, "4xx": 0, "5xx": 0, "other": 0}
    assert report["duration"] == {"count": 0, "mean": 0.0, "p50": 0.0, "p95": 0.0, "max": 0.0}


def test_blank_lines_ignored_and_malformed_counted():
    report = logstats.analyze([GOOD, "", "   \n", "garbage"])
    assert report["lines_total"] == 2
    assert report["lines_parsed"] == 1
    assert report["lines_malformed"] == 1


def test_methods_sorted_and_only_seen():
    report = logstats.analyze([_line(method="POST"), _line(method="GET"), _line(method="DELETE")])
    assert report["methods"] == {"DELETE": 1, "GET": 1, "POST": 1}
    assert list(report["methods"]) == ["DELETE", "GET", "POST"]


def test_top_truncation_and_tie_breaking():
    lines = [
        _line(path="/b", ip="2.2.2.2"),
        _line(path="/a", ip="3.3.3.3"),
        _line(path="/c", ip="1.1.1.1"),
        _line(path="/a", ip="3.3.3.3"),
        _line(path="/b", ip="2.2.2.2"),
    ]
    report = logstats.analyze(lines, top=2)
    assert report["top_paths"] == [{"path": "/a", "count": 2}, {"path": "/b", "count": 2}]
    assert report["top_ips"] == [{"ip": "2.2.2.2", "count": 2}, {"ip": "3.3.3.3", "count": 2}]


def test_bytes_total_sums_parsed_only():
    report = logstats.analyze([_line("200 10 1.0"), _line("200 5 1.0"), "junk"])
    assert report["bytes_total"] == 15


def _write(tmp_path, text):
    p = tmp_path / "access.log"
    p.write_text(text, encoding="utf-8")
    return str(p)


def test_cli_json_output(tmp_path, capsys):
    path = _write(tmp_path, GOOD + "\njunk\n\n")
    assert logstats.main([path, "--top", "1"]) == 0
    out = capsys.readouterr().out
    assert out.endswith("}\n")
    data = json.loads(out)
    assert data["lines_total"] == 2
    assert data["lines_malformed"] == 1
    assert len(data["top_paths"]) == 1


def test_cli_table_output(tmp_path, capsys):
    path = _write(tmp_path, GOOD + "\n")
    assert logstats.main([path, "--format", "table"]) == 0
    out = capsys.readouterr().out
    for token in ("lines_total", "status_classes", "top_paths", "top_ips", "duration"):
        assert token in out
    with pytest.raises(ValueError):
        json.loads(out)


def test_cli_strict_exits_2_on_first_malformed(tmp_path, capsys):
    path = _write(tmp_path, GOOD + "\n\njunk here\n" + GOOD + "\nmore junk\n")
    assert logstats.main([path, "--strict"]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "malformed line 3: junk here\n"


def test_cli_strict_passes_on_clean_file(tmp_path, capsys):
    path = _write(tmp_path, GOOD + "\n")
    assert logstats.main([path, "--strict"]) == 0


def test_cli_missing_file_exits_2(tmp_path, capsys):
    assert logstats.main([str(tmp_path / "nope.log")]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err != ""


@pytest.mark.parametrize("bad", ["0", "-3", "abc"])
def test_cli_invalid_top_exits_2(tmp_path, capsys, bad):
    path = _write(tmp_path, GOOD + "\n")
    assert logstats.main([path, "--top", bad]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err != ""


def test_import_has_no_side_effects(capsys):
    assert capsys.readouterr().out == ""
