import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import logstats


def test_well_formed_line_parsed_field_by_field():
    rec = logstats.parse_line(
        '203.0.113.10 - - [09/Sep/2026:08:00:01 +0800] '
        '"GET /api/users HTTP/1.1" 200 1024 0.042'
    )
    assert rec["ip"] == "203.0.113.10"
    assert rec["user"] is None
    assert rec["method"] == "GET"
    assert rec["path"] == "/api/users"
    assert rec["protocol"] == "HTTP/1.1"
    assert rec["status"] == 200
    assert rec["bytes"] == 1024
    assert rec["duration"] == 0.042
    assert rec["timestamp"].utcoffset().total_seconds() == 8 * 3600


def test_malformed_line_returns_none():
    assert logstats.parse_line("this line is not a log line at all") is None


def test_trailing_newline_tolerated():
    line = (
        '198.51.100.7 - alice [09/Sep/2026:08:00:03 +0800] '
        '"GET / HTTP/1.1" 304 - 0.011'
    )
    assert logstats.parse_line(line + "\n") is not None
    assert logstats.parse_line(line + "\r\n") is not None


def test_bytes_dash_becomes_zero_and_user_kept():
    rec = logstats.parse_line(
        '198.51.100.7 - alice [09/Sep/2026:08:00:03 +0800] '
        '"GET / HTTP/1.1" 304 - 0.011'
    )
    assert rec["bytes"] == 0
    assert rec["user"] == "alice"


def test_percentile_nearest_rank():
    lines = [
        '1.1.1.1 - - [09/Sep/2026:08:00:01 +0800] "GET /a HTTP/1.1" 200 1 1.0',
        '1.1.1.1 - - [09/Sep/2026:08:00:02 +0800] "GET /a HTTP/1.1" 200 1 2.0',
        '1.1.1.1 - - [09/Sep/2026:08:00:03 +0800] "GET /a HTTP/1.1" 200 1 3.0',
        '1.1.1.1 - - [09/Sep/2026:08:00:04 +0800] "GET /a HTTP/1.1" 200 1 4.0',
    ]
    r = logstats.analyze(lines)
    assert r["duration"]["p50"] == 2.0
    assert r["duration"]["p95"] == 4.0
    assert r["status_classes"] == {"2xx": 4, "3xx": 0, "4xx": 0, "5xx": 0, "other": 0}


def test_top_truncation_and_tie_breaking():
    lines = [
        '1.1.1.1 - - [09/Sep/2026:08:00:01 +0800] "GET /b HTTP/1.1" 200 1 0.1',
        '1.1.1.1 - - [09/Sep/2026:08:00:02 +0800] "GET /a HTTP/1.1" 200 1 0.1',
        '1.1.1.1 - - [09/Sep/2026:08:00:03 +0800] "GET /c HTTP/1.1" 200 1 0.1',
        '1.1.1.1 - - [09/Sep/2026:08:00:04 +0800] "GET /c HTTP/1.1" 200 1 0.1',
    ]
    r = logstats.analyze(lines, top=2)
    # /c has count 2 (highest), /a and /b tie at 1 -> alphabetical -> /a wins
    assert r["top_paths"] == [
        {"path": "/c", "count": 2},
        {"path": "/a", "count": 1},
    ]
    assert len(r["top_paths"]) == 2


def test_blank_lines_ignored():
    lines = [
        "",
        "   ",
        '1.1.1.1 - - [09/Sep/2026:08:00:01 +0800] "GET /a HTTP/1.1" 200 1 0.1',
    ]
    r = logstats.analyze(lines)
    assert r["lines_total"] == 1
    assert r["lines_parsed"] == 1
    assert r["lines_malformed"] == 0


def test_no_lines_duration_defaults():
    r = logstats.analyze([])
    assert r["duration"] == {"count": 0, "mean": 0.0, "p50": 0.0, "p95": 0.0, "max": 0.0}
    assert r["lines_total"] == 0


def test_status_other_class():
    lines = [
        '1.1.1.1 - - [09/Sep/2026:08:00:01 +0800] "GET /a HTTP/1.1" 999 1 0.1',
    ]
    r = logstats.analyze(lines)
    assert r["status_classes"]["other"] == 1


def test_methods_sorted_ascending():
    lines = [
        '1.1.1.1 - - [09/Sep/2026:08:00:01 +0800] "POST /a HTTP/1.1" 200 1 0.1',
        '1.1.1.1 - - [09/Sep/2026:08:00:02 +0800] "GET /a HTTP/1.1" 200 1 0.1',
    ]
    r = logstats.analyze(lines)
    assert list(r["methods"].keys()) == ["GET", "POST"]


def test_cli_strict_exits_2_on_malformed(tmp_path):
    log_file = tmp_path / "bad.log"
    log_file.write_text(
        '1.1.1.1 - - [09/Sep/2026:08:00:01 +0800] "GET /a HTTP/1.1" 200 1 0.1\n'
        "not a valid log line\n"
    )
    result = subprocess.run(
        [sys.executable, str(Path(__file__).resolve().parent.parent / "logstats.py"),
         str(log_file), "--strict"],
        capture_output=True, text=True,
    )
    assert result.returncode == 2
    assert result.stdout == ""
    assert "malformed line 2" in result.stderr


def test_cli_missing_file_exits_2(tmp_path):
    missing = tmp_path / "does_not_exist.log"
    result = subprocess.run(
        [sys.executable, str(Path(__file__).resolve().parent.parent / "logstats.py"),
         str(missing)],
        capture_output=True, text=True,
    )
    assert result.returncode == 2
    assert result.stdout == ""


def test_cli_invalid_top_exits_2(tmp_path):
    log_file = tmp_path / "ok.log"
    log_file.write_text(
        '1.1.1.1 - - [09/Sep/2026:08:00:01 +0800] "GET /a HTTP/1.1" 200 1 0.1\n'
    )
    result = subprocess.run(
        [sys.executable, str(Path(__file__).resolve().parent.parent / "logstats.py"),
         str(log_file), "--top", "0"],
        capture_output=True, text=True,
    )
    assert result.returncode == 2
    assert result.stdout == ""


def test_cli_table_format_not_json(tmp_path):
    log_file = tmp_path / "ok.log"
    log_file.write_text(
        '1.1.1.1 - - [09/Sep/2026:08:00:01 +0800] "GET /a HTTP/1.1" 200 1 0.1\n'
    )
    result = subprocess.run(
        [sys.executable, str(Path(__file__).resolve().parent.parent / "logstats.py"),
         str(log_file), "--format", "table"],
        capture_output=True, text=True,
    )
    assert result.returncode == 0
    for substr in ["lines_total", "status_classes", "top_paths", "top_ips", "duration"]:
        assert substr in result.stdout
    try:
        json.loads(result.stdout)
        is_json = True
    except json.JSONDecodeError:
        is_json = False
    assert not is_json
