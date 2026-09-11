"""Reference test suite (8 tests)."""
import json
import subprocess
import sys

import pytest

import logstats

GOOD = '203.0.113.10 - - [09/Sep/2026:08:00:01 +0800] "GET /api/users HTTP/1.1" 200 1024 0.042'


def line(path="/a", status=200, size=1, dur=0.5, ip="1.1.1.1"):
    return f'{ip} - - [09/Sep/2026:08:00:01 +0800] "GET {path} HTTP/1.1" {status} {size} {dur}'


def test_parse_good_line_fields():
    rec = logstats.parse_line(GOOD)
    assert rec["ip"] == "203.0.113.10"
    assert rec["method"] == "GET"
    assert rec["status"] == 200
    assert rec["duration"] == 0.042


def test_malformed_returns_none():
    assert logstats.parse_line("nope") is None


def test_dash_bytes_is_zero():
    rec = logstats.parse_line(
        '1.1.1.1 - - [09/Sep/2026:08:00:01 +0800] "GET / HTTP/1.1" 304 - 0.011'
    )
    assert rec["bytes"] == 0


def test_dash_user_is_none():
    assert logstats.parse_line(GOOD)["user"] is None


def test_nearest_rank_percentile():
    r = logstats.analyze([line(dur=d) for d in (1.0, 2.0, 3.0, 4.0)])
    assert r["duration"]["p50"] == 2.0
    assert r["duration"]["p95"] == 4.0


def test_top_truncation_and_tie_break():
    rows = [line(path="/b")] * 2 + [line(path="/a")] * 2 + [line(path="/c")]
    r = logstats.analyze(rows, top=2)
    assert [x["path"] for x in r["top_paths"]] == ["/a", "/b"]


def test_strict_exits_2(tmp_path):
    log = tmp_path / "x.log"
    log.write_text(line() + "\nbroken\n", encoding="utf-8")
    p = subprocess.run(
        [sys.executable, "logstats.py", str(log), "--strict"],
        capture_output=True, text=True, timeout=60,
    )
    assert p.returncode == 2
    assert p.stdout == ""


def test_missing_file_exits_2():
    p = subprocess.run(
        [sys.executable, "logstats.py", "nope.log"],
        capture_output=True, text=True, timeout=60,
    )
    assert p.returncode == 2
