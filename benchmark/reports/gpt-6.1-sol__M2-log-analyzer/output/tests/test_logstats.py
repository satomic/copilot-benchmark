import datetime
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

import logstats


def _line(ip="203.0.113.10", user="-", method="GET", path="/api/users",
          status=200, byte_count="1024", duration="0.042"):
    return (
        f'{ip} - {user} [09/Sep/2026:08:00:01 +0800] '
        f'"{method} {path} HTTP/1.1" {status:03d} {byte_count} {duration}'
    )


def test_parse_all_fields():
    assert logstats.parse_line(_line(user="alice_1")) == {
        "ip": "203.0.113.10",
        "user": "alice_1",
        "timestamp": datetime.datetime(
            2026, 9, 9, 8, 0, 1,
            tzinfo=datetime.timezone(datetime.timedelta(hours=8)),
        ),
        "method": "GET",
        "path": "/api/users",
        "protocol": "HTTP/1.1",
        "status": 200,
        "bytes": 1024,
        "duration": 0.042,
    }


def test_anonymous_user_and_missing_bytes():
    record = logstats.parse_line(_line(byte_count="-"))
    assert record["user"] is None
    assert record["bytes"] == 0


@pytest.mark.parametrize("terminator", ["", "\n", "\r\n", "\r"])
def test_trailing_line_terminators(terminator):
    assert logstats.parse_line(_line() + terminator) == logstats.parse_line(_line())


@pytest.mark.parametrize("line", [
    "this line is not a log line at all", "", "   ",
    _line() + " junk", " " + _line(), _line() + " ",
    _line(ip="256.0.0.1"), _line(method="get"), _line(path="/a b"),
    _line(byte_count="-1"), _line(duration="abc"), _line(duration="-0.1"),
    _line().replace("09/Sep", "31/Sep"),
    _line().replace("Sep", "Foo"),
    _line().replace("+0800", "+0860"),
    _line().replace("+0800", "+2400"),
    _line().replace("08:00:01", "25:00:01"),
    _line().replace("HTTP/1.1", "HTTP/bad"),
    _line().replace(" 200 ", " 2000 "),
    _line() + "\n\n",
])
def test_malformed_lines(line):
    assert logstats.parse_line(line) is None


def test_negative_timezone_and_leap_day():
    line = _line().replace("09/Sep/2026", "29/Feb/2024").replace("+0800", "-0530")
    timestamp = logstats.parse_line(line)["timestamp"]
    assert timestamp.day == 29
    assert timestamp.utcoffset() == -datetime.timedelta(hours=5, minutes=30)


def test_percentiles_nearest_rank_and_rounding():
    report = logstats.analyze(_line(duration=str(value)) for value in [4, 1, 3, 2])
    assert report["duration"] == {
        "count": 4, "mean": 2.5, "p50": 2.0, "p95": 4.0, "max": 4.0,
    }
    single = logstats.analyze([_line(duration="0.12345")])
    assert single["duration"] == {
        "count": 1, "mean": 0.123, "p50": 0.123, "p95": 0.123, "max": 0.123,
    }
    twenty = logstats.analyze(_line(duration=str(value)) for value in range(1, 21))
    assert twenty["duration"]["p50"] == 10.0
    assert twenty["duration"]["p95"] == 19.0


def test_top_truncation_and_lexical_ties():
    report = logstats.analyze([
        _line(ip="2.0.0.1", path="/b"),
        _line(ip="10.0.0.1", path="/a"),
        _line(ip="3.0.0.1", path="/c"),
        _line(ip="3.0.0.1", path="/c"),
    ], top=2)
    assert report["top_paths"] == [{"path": "/c", "count": 2}, {"path": "/a", "count": 1}]
    assert report["top_ips"] == [{"ip": "3.0.0.1", "count": 2}, {"ip": "10.0.0.1", "count": 1}]
    assert len(logstats.analyze([_line()], top=10)["top_paths"]) == 1


def test_counts_status_classes_and_method_order():
    statuses = [199, 200, 299, 300, 399, 400, 499, 500, 599, 600, 999]
    report = logstats.analyze(
        ["\n", " \t\r\n", "bad\n"]
        + [_line(status=status, method="POST" if i % 2 else "GET", byte_count="2")
           for i, status in enumerate(statuses)]
    )
    assert list(report) == [
        "lines_total", "lines_parsed", "lines_malformed", "bytes_total",
        "status_classes", "methods", "top_paths", "top_ips", "duration",
    ]
    assert report["lines_total"] == 12
    assert report["lines_parsed"] == 11
    assert report["lines_malformed"] == 1
    assert report["bytes_total"] == 22
    assert report["status_classes"] == {"2xx": 2, "3xx": 2, "4xx": 2, "5xx": 2, "other": 3}
    assert list(report["methods"]) == ["GET", "POST"]
    assert report["methods"] == {"GET": 6, "POST": 5}


def test_no_parsed_lines():
    report = logstats.analyze(["", " \n", "bad"])
    assert report["lines_total"] == report["lines_malformed"] == 1
    assert report["lines_parsed"] == report["bytes_total"] == 0
    assert report["status_classes"] == {"2xx": 0, "3xx": 0, "4xx": 0, "5xx": 0, "other": 0}
    assert report["methods"] == {}
    assert report["top_paths"] == report["top_ips"] == []
    assert report["duration"] == {"count": 0, "mean": 0.0, "p50": 0.0, "p95": 0.0, "max": 0.0}


def test_cli_json_default_and_non_strict(tmp_path, capsys):
    source = tmp_path / "input.log"
    lines = [_line() + "\n", "bad\n", "\n"]
    source.write_text("".join(lines), encoding="utf-8")
    assert logstats.main([str(source), "--top", "3"]) == 0
    output = capsys.readouterr()
    assert output.err == ""
    assert output.out == json.dumps(logstats.analyze(lines, top=3), indent=2) + "\n"


def test_cli_strict_first_malformed_line(tmp_path, capsys):
    source = tmp_path / "input.log"
    source.write_bytes(("\r\n" + _line() + "\r\nbad  \r\nanother bad\r\n").encode())
    assert logstats.main([str(source), "--strict"]) == 2
    output = capsys.readouterr()
    assert output.out == ""
    assert output.err == "malformed line 3: bad  \n"


def test_cli_strict_valid_input(tmp_path, capsys):
    source = tmp_path / "input.log"
    source.write_text("\n" + _line() + "\n", encoding="utf-8")
    assert logstats.main([str(source), "--strict"]) == 0
    output = capsys.readouterr()
    assert output.err == ""
    assert json.loads(output.out)["lines_parsed"] == 1


def test_cli_missing_file(tmp_path, capsys):
    assert logstats.main([str(tmp_path / "missing.log")]) == 2
    output = capsys.readouterr()
    assert output.out == ""
    assert output.err


def test_cli_unreadable_path(tmp_path, capsys):
    assert logstats.main([str(tmp_path)]) == 2
    output = capsys.readouterr()
    assert output.out == ""
    assert output.err


@pytest.mark.parametrize("top", ["0", "-1", "abc", "1.5"])
def test_cli_invalid_top(top, capsys):
    assert logstats.main(["unused.log", "--top", top]) == 2
    output = capsys.readouterr()
    assert output.out == ""
    assert "positive integer" in output.err


def test_cli_table(tmp_path, capsys):
    source = tmp_path / "input.log"
    source.write_text(_line(), encoding="utf-8")
    assert logstats.main([str(source), "--format", "table"]) == 0
    output = capsys.readouterr()
    assert output.err == ""
    for key in ("lines_total", "status_classes", "top_paths", "top_ips", "duration"):
        assert key in output.out
    with pytest.raises(json.JSONDecodeError):
        json.loads(output.out)


def test_import_has_no_side_effects_and_script_exit_code(tmp_path):
    environment = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    imported = subprocess.run(
        [sys.executable, "-c", "import logstats"],
        capture_output=True, text=True, env=environment, check=False,
    )
    assert imported.returncode == 0
    assert imported.stdout == imported.stderr == ""
    source = tmp_path / "input.log"
    source.write_text("bad\n", encoding="utf-8")
    result = subprocess.run(
        [sys.executable, str(Path(logstats.__file__)), str(source), "--strict"],
        capture_output=True, text=True, env=environment, check=False,
    )
    assert result.returncode == 2
    assert result.stdout == ""
    assert result.stderr == "malformed line 1: bad\n"


def test_only_requested_api_is_public():
    assert {name for name in vars(logstats) if not name.startswith("_")} == {
        "parse_line", "analyze", "main",
    }
