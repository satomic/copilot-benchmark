"""Tests for logstats.py"""

import datetime
import json
import sys

import pytest

from logstats import analyze, parse_line, main


# ---------------------------------------------------------------------------
# Well-formed line -> field-by-field
# ---------------------------------------------------------------------------

class TestParseLine:
    def test_well_formed(self):
        line = (
            '203.0.113.10 - - [09/Sep/2026:08:00:01 +0800] '
            '"GET /api/users HTTP/1.1" 200 1024 0.042'
        )
        rec = parse_line(line)
        assert rec is not None
        assert rec["ip"] == "203.0.113.10"
        assert rec["user"] is None
        assert rec["method"] == "GET"
        assert rec["path"] == "/api/users"
        assert rec["protocol"] == "HTTP/1.1"
        assert rec["status"] == 200
        assert rec["bytes"] == 1024
        assert rec["duration"] == 0.042
        assert rec["timestamp"].year == 2026
        assert rec["timestamp"].month == 9
        assert rec["timestamp"].day == 9
        assert rec["timestamp"].hour == 8
        assert rec["timestamp"].minute == 0
        assert rec["timestamp"].second == 1
        assert rec["timestamp"].utcoffset().total_seconds() == 8 * 3600

    def test_malformed_returns_none(self):
        assert parse_line("this line is not a log line at all") is None
        assert parse_line("") is None
        assert parse_line("   ") is None

    def test_bytes_dash_becomes_zero(self):
        line = (
            '198.51.100.7 - alice [09/Sep/2026:08:00:03 +0800] '
            '"GET / HTTP/1.1" 304 - 0.011'
        )
        rec = parse_line(line)
        assert rec is not None
        assert rec["bytes"] == 0
        assert rec["user"] == "alice"

    def test_named_user(self):
        line = (
            '198.51.100.7 - bob [09/Sep/2026:08:00:17 +0800] '
            '"GET / HTTP/1.1" 304 - 0.011'
        )
        rec = parse_line(line)
        assert rec is not None
        assert rec["user"] == "bob"

    def test_trailing_newline(self):
        line = (
            '203.0.113.10 - - [09/Sep/2026:08:00:01 +0800] '
            '"GET /api/users HTTP/1.1" 200 1024 0.042\n'
        )
        rec = parse_line(line)
        assert rec is not None
        assert rec["ip"] == "203.0.113.10"

        line_crlf = (
            '203.0.113.10 - - [09/Sep/2026:08:00:01 +0800] '
            '"GET /api/users HTTP/1.1" 200 1024 0.042\r\n'
        )
        rec2 = parse_line(line_crlf)
        assert rec2 is not None
        assert rec2["ip"] == "203.0.113.10"


# ---------------------------------------------------------------------------
# analyze
# ---------------------------------------------------------------------------

class TestAnalyze:
    def test_percentile_rule(self):
        lines = [
            '1.1.1.1 - - [09/Sep/2026:08:00:01 +0800] "GET /a HTTP/1.1" 200 1 1.0',
            '1.1.1.1 - - [09/Sep/2026:08:00:02 +0800] "GET /a HTTP/1.1" 200 1 2.0',
            '1.1.1.1 - - [09/Sep/2026:08:00:03 +0800] "GET /a HTTP/1.1" 200 1 3.0',
            '1.1.1.1 - - [09/Sep/2026:08:00:04 +0800] "GET /a HTTP/1.1" 200 1 4.0',
        ]
        r = analyze(lines)
        assert r["duration"]["p50"] == 2.0
        assert r["duration"]["p95"] == 4.0
        assert r["status_classes"] == {
            "2xx": 4, "3xx": 0, "4xx": 0, "5xx": 0, "other": 0
        }

    def test_top_truncation_and_tie_breaking(self):
        """top_paths sorted by count desc then path asc; top=2 truncates."""
        lines = [
            '1.1.1.1 - - [09/Sep/2026:08:00:01 +0800] "GET /z HTTP/1.1" 200 1 1.0',
            '2.2.2.2 - - [09/Sep/2026:08:00:02 +0800] "GET /a HTTP/1.1" 200 1 0.1',
            '1.1.1.1 - - [09/Sep/2026:08:00:03 +0800] "GET /z HTTP/1.1" 200 1 1.0',
            '3.3.3.3 - - [09/Sep/2026:08:00:04 +0800] "GET /m HTTP/1.1" 200 1 0.2',
            '4.4.4.4 - - [09/Sep/2026:08:00:05 +0800] "GET /a HTTP/1.1" 200 1 0.1',
                '2.2.2.2 - - [09/Sep/2026:08:00:06 +0800] "GET /b HTTP/1.1" 200 1 0.1',
        ]
        r = analyze(lines, top=2)
            # paths: /a=2, /z=2, /m=1, /b=1
        # top 2: /a (count=2) and /z (count=2), /a comes first due to alpha
        assert r["top_paths"] == [
            {"path": "/a", "count": 2},
            {"path": "/z", "count": 2},
        ]
        # IPs: 1.1.1.1=2, 2.2.2.2=2, 3.3.3.3=1, 4.4.4.4=1
        # top 2: 1.1.1.1 (count=2) and 2.2.2.2 (count=2)
        assert r["top_ips"] == [
            {"ip": "1.1.1.1", "count": 2},
            {"ip": "2.2.2.2", "count": 2},
        ]

    def test_status_classes_all_present(self):
        lines = [
            '1.1.1.1 - - [09/Sep/2026:08:00:01 +0800] "GET /a HTTP/1.1" 103 1 0.1',
            '1.1.1.1 - - [09/Sep/2026:08:00:02 +0800] "GET /a HTTP/1.1" 200 1 0.1',
            '1.1.1.1 - - [09/Sep/2026:08:00:03 +0800] "GET /a HTTP/1.1" 301 1 0.1',
            '1.1.1.1 - - [09/Sep/2026:08:00:04 +0800] "GET /a HTTP/1.1" 403 1 0.1',
            '1.1.1.1 - - [09/Sep/2026:08:00:05 +0800] "GET /a HTTP/1.1" 500 1 0.1',
            '1.1.1.1 - - [09/Sep/2026:08:00:06 +0800] "GET /a HTTP/1.1" 600 1 0.1',
        ]
        r = analyze(lines)
        assert r["status_classes"] == {
            "2xx": 1, "3xx": 1, "4xx": 1, "5xx": 1, "other": 2
        }

    def test_empty_input(self):
        r = analyze([])
        assert r["lines_total"] == 0
        assert r["lines_parsed"] == 0
        assert r["lines_malformed"] == 0
        assert r["bytes_total"] == 0
        assert r["duration"] == {
            "count": 0, "mean": 0.0, "p50": 0.0, "p95": 0.0, "max": 0.0
        }
        assert r["status_classes"] == {
            "2xx": 0, "3xx": 0, "4xx": 0, "5xx": 0, "other": 0
        }
        assert r["methods"] == {}
        assert r["top_paths"] == []
        assert r["top_ips"] == []

    def test_malformed_skipped(self):
        lines = [
            '1.1.1.1 - - [09/Sep/2026:08:00:01 +0800] "GET /a HTTP/1.1" 200 1 1.0',
            "garbage line",
            '1.1.1.1 - - [09/Sep/2026:08:00:02 +0800] "GET /a HTTP/1.1" 200 1 2.0',
            "",
            "  ",
        ]
        r = analyze(lines)
        assert r["lines_total"] == 3  # blank lines don't count
        assert r["lines_parsed"] == 2
        assert r["lines_malformed"] == 1
        assert r["duration"]["mean"] == 1.5


# ---------------------------------------------------------------------------
# CLI — strict, missing file, bad --top
# ---------------------------------------------------------------------------

class TestCLI:
    def test_strict_exits_2_on_malformed(self, tmp_path, capsys):
        log = tmp_path / "test.log"
        log.write_text(
            '1.1.1.1 - - [09/Sep/2026:08:00:01 +0800] "GET /a HTTP/1.1" 200 1 1.0\n'
            "bad line\n"
            '1.1.1.1 - - [09/Sep/2026:08:00:02 +0800] "GET /a HTTP/1.1" 200 1 2.0\n'
        )
        rc = main([str(log), "--strict"])
        captured = capsys.readouterr()
        assert rc == 2
        assert captured.out == ""
        assert "malformed line 2: bad line" in captured.err

    def test_missing_file_exits_2(self, capsys):
        rc = main(["nonexistent.log"])
        captured = capsys.readouterr()
        assert rc == 2
        assert captured.out == ""
        assert "error" in captured.err.lower()

    def test_bad_top_exits_2(self, capsys):
        rc = main(["access.log", "--top", "0"])
        captured = capsys.readouterr()
        assert rc == 2
        assert captured.out == ""

    def test_sample_log_from_task(self):
        """Run against the provided access.log with --top 3."""
        rc = main(["access.log", "--top", "3"])
        assert rc == 0

    def test_sample_log_json_output(self, capsys):
        rc = main(["access.log", "--top", "3", "--format", "json"])
        captured = capsys.readouterr()
        assert rc == 0
        report = json.loads(captured.out)
        assert report["lines_total"] == 40
        assert report["lines_malformed"] == 4
        assert report["lines_parsed"] == 36


# ---------------------------------------------------------------------------
# Importing has no side effects (CLI guard)
# ---------------------------------------------------------------------------

def test_import_no_side_effects():
    """Importing logstats must not trigger CLI execution."""
    import subprocess
    result = subprocess.run(
        [sys.executable, "-c", "import logstats; print('ok')"],
        capture_output=True,
        text=True,
        cwd=".",
    )
    assert result.returncode == 0
    assert result.stdout.strip() == "ok"