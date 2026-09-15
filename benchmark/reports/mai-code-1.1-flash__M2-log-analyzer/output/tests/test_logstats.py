import json
import subprocess
import sys
from pathlib import Path

import logstats

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_parse_line_valid_record_fields():
    record = logstats.parse_line(
        '203.0.113.10 - - [09/Sep/2026:08:00:01 +0800] "GET /api/users HTTP/1.1" 200 1024 0.042'
    )
    assert record is not None
    assert record["ip"] == "203.0.113.10"
    assert record["user"] is None
    assert record["timestamp"].utcoffset().total_seconds() == 8 * 3600
    assert record["method"] == "GET"
    assert record["path"] == "/api/users"
    assert record["protocol"] == "HTTP/1.1"
    assert record["status"] == 200
    assert record["bytes"] == 1024
    assert record["duration"] == 0.042


def test_parse_line_malformed_returns_none():
    assert logstats.parse_line("this line is not a log line at all") is None


def test_bytes_dash_becomes_zero():
    record = logstats.parse_line(
        '198.51.100.7 - alice [09/Sep/2026:08:00:03 +0800] "GET / HTTP/1.1" 304 - 0.011'
    )
    assert record is not None
    assert record["bytes"] == 0
    assert record["user"] == "alice"


def test_user_dash_becomes_none():
    record = logstats.parse_line(
        '203.0.113.10 - - [09/Sep/2026:08:00:01 +0800] "GET /api/users HTTP/1.1" 200 1024 0.042'
    )
    assert record is not None
    assert record["user"] is None


def test_percentile_rules_nearest_rank():
    report = logstats.analyze([
        '1.1.1.1 - - [09/Sep/2026:08:00:01 +0800] "GET /a HTTP/1.1" 200 1 1.0',
        '1.1.1.1 - - [09/Sep/2026:08:00:02 +0800] "GET /a HTTP/1.1" 200 1 2.0',
        '1.1.1.1 - - [09/Sep/2026:08:00:03 +0800] "GET /a HTTP/1.1" 200 1 3.0',
        '1.1.1.1 - - [09/Sep/2026:08:00:04 +0800] "GET /a HTTP/1.1" 200 1 4.0',
    ])
    assert report["duration"]["p50"] == 2.0
    assert report["duration"]["p95"] == 4.0
    assert report["status_classes"] == {"2xx": 4, "3xx": 0, "4xx": 0, "5xx": 0, "other": 0}


def test_top_truncation_and_tie_breaking():
    report = logstats.analyze([
        '1.1.1.1 - - [09/Sep/2026:08:00:01 +0800] "GET /a HTTP/1.1" 200 1 1.0',
        '2.2.2.2 - - [09/Sep/2026:08:00:02 +0800] "GET /b HTTP/1.1" 200 1 2.0',
        '3.3.3.3 - - [09/Sep/2026:08:00:03 +0800] "GET /b HTTP/1.1" 200 1 3.0',
        '4.4.4.4 - - [09/Sep/2026:08:00:04 +0800] "GET /c HTTP/1.1" 200 1 4.0',
        '5.5.5.5 - - [09/Sep/2026:08:00:05 +0800] "GET /c HTTP/1.1" 200 1 5.0',
    ], top=2)
    assert report["top_paths"] == [{"path": "/b", "count": 2}, {"path": "/c", "count": 2}]
    assert report["top_ips"] == [{"ip": "1.1.1.1", "count": 1}, {"ip": "2.2.2.2", "count": 1}]


def test_analyze_ignores_blank_lines_and_counts_malformed():
    report = logstats.analyze([
        "\n",
        '1.1.1.1 - - [09/Sep/2026:08:00:01 +0800] "GET /a HTTP/1.1" 200 1 1.0',
        "  \t",
        'bad line',
        '2.2.2.2 - - [09/Sep/2026:08:00:02 +0800] "POST /b HTTP/1.1" 201 2 0.25',
    ])
    assert report["lines_total"] == 3
    assert report["lines_parsed"] == 2
    assert report["lines_malformed"] == 1
    assert report["bytes_total"] == 3


def test_main_strict_exits_2_and_reports_malformed_line(tmp_path):
    path = tmp_path / "sample.log"
    path.write_text(
        '1.1.1.1 - - [09/Sep/2026:08:00:01 +0800] "GET /one HTTP/1.1" 200 10 0.1\n'
        'bad line\n',
        encoding="utf-8",
    )
    completed = subprocess.run(
        [sys.executable, "logstats.py", str(path), "--strict"],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 2
    assert completed.stdout == ""
    assert "malformed line 2: bad line" in completed.stderr


def test_main_missing_file_exits_2():
    completed = subprocess.run(
        [sys.executable, "logstats.py", "missing.log"],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 2
    assert completed.stdout == ""
    assert "error:" in completed.stderr


def test_main_invalid_top_exits_2():
    completed = subprocess.run(
        [sys.executable, "logstats.py", "access.log", "--top", "0"],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 2
    assert completed.stdout == ""
    assert "--top" in completed.stderr


def test_cli_json_sample_has_expected_totals():
    completed = subprocess.run(
        [sys.executable, "logstats.py", "access.log", "--top", "3"],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0
    payload = json.loads(completed.stdout)
    assert payload["lines_total"] == 40
    assert payload["lines_malformed"] == 4
    assert payload["lines_parsed"] == 36


def test_parse_line_accepts_trailing_newline():
    record = logstats.parse_line(
        '203.0.113.10 - - [09/Sep/2026:08:00:01 +0800] "GET /api/users HTTP/1.1" 200 1024 0.042\n'
    )
    assert record is not None
    assert record["path"] == "/api/users"


def test_parse_line_rejects_invalid_ipv4_and_bad_status():
    assert logstats.parse_line('999.0.0.1 - - [09/Sep/2026:08:00:01 +0800] "GET / HTTP/1.1" 200 1 1.0') is None
    assert logstats.parse_line('1.1.1.1 - - [09/Sep/2026:08:00:01 +0800] "GET / HTTP/1.1" 99 1 1.0') is None
