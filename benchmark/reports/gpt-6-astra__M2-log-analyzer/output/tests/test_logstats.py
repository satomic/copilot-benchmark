import datetime
import io
import json
import subprocess
import sys
from unittest.mock import patch

import logstats


def _line(ip="203.0.113.10", user="-", method="GET", path="/api/users",
          status=200, size="1024", duration="0.042"):
    return (
        f'{ip} - {user} [09/Sep/2026:08:00:01 +0800] '
        f'"{method} {path} HTTP/1.1" {status:03d} {size} {duration}'
    )


def _run(text, args=()):
    with patch("builtins.open", return_value=io.StringIO(text)) as opened:
        result = logstats.main(["fixture.log", *args])
    opened.assert_called_once_with("fixture.log", encoding="utf-8")
    return result


def test_parse_every_field():
    record = logstats.parse_line(_line(user="alice_7"))
    assert record == {
        "ip": "203.0.113.10",
        "user": "alice_7",
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
    assert record["timestamp"].utcoffset().total_seconds() == 8 * 3600
    for key in ("status", "bytes"):
        assert type(record[key]) is int
    assert type(record["duration"]) is float


def test_parse_anonymous_and_missing_bytes():
    record = logstats.parse_line(_line(size="-"))
    assert record["user"] is None
    assert record["bytes"] == 0
    record = logstats.parse_line(_line(user="alice", size="-", status=304))
    assert record["user"] == "alice"
    assert record["bytes"] == 0


def test_parse_line_terminators():
    expected = logstats.parse_line(_line())
    for ending in ("\n", "\r\n"):
        assert logstats.parse_line(_line() + ending) == expected


def test_malformed_lines():
    for line in (
        "this line is not a log line at all", "", " \t",
        _line() + " garbage", " " + _line(), _line() + " ",
        _line() + "\n\n", _line(method="get"), _line(path="/has space"),
        _line(size="-1"), _line(duration="abc"), _line(duration="-0.1"),
        _line(duration="NaN"), _line(duration="1e3"), _line(status=1000),
        _line(ip="256.1.1.1"), _line(ip="1.2.3"),
        _line().replace("09/Sep", "31/Sep"),
        _line().replace("Sep", "Bad"), _line().replace("+0800", "+0860"),
        _line().replace("+0800", "+2400"),
        _line().replace("08:00:01", "25:00:01"),
    ):
        assert logstats.parse_line(line) is None, line


def test_negative_timezone_and_leap_day():
    record = logstats.parse_line(
        _line().replace("09/Sep/2026", "29/Feb/2024").replace("+0800", "-0530")
    )
    assert record["timestamp"].day == 29
    assert record["timestamp"].utcoffset() == datetime.timedelta(hours=-5, minutes=-30)
    assert logstats.parse_line(_line().replace("09/Sep/2026", "29/Feb/2026")) is None


def test_report_shape_and_empty_input():
    report = logstats.analyze(iter(["", "\n", " \t\r\n"]))
    assert list(report) == [
        "lines_total", "lines_parsed", "lines_malformed", "bytes_total",
        "status_classes", "methods", "top_paths", "top_ips", "duration",
    ]
    assert report == {
        "lines_total": 0, "lines_parsed": 0, "lines_malformed": 0,
        "bytes_total": 0,
        "status_classes": {"2xx": 0, "3xx": 0, "4xx": 0, "5xx": 0, "other": 0},
        "methods": {}, "top_paths": [], "top_ips": [],
        "duration": {"count": 0, "mean": 0.0, "p50": 0.0, "p95": 0.0, "max": 0.0},
    }
    assert list(report["status_classes"]) == ["2xx", "3xx", "4xx", "5xx", "other"]


def test_counts_classes_and_method_order():
    statuses = (0, 199, 200, 299, 300, 399, 400, 499, 500, 599, 600, 999)
    lines = [
        _line(status=status, size="2", method="POST" if i % 2 else "GET") + "\n"
        for i, status in enumerate(statuses)
    ]
    report = logstats.analyze(iter(["\n", "bad\n", *lines, " \t", "also bad"]))
    assert (report["lines_total"], report["lines_parsed"], report["lines_malformed"]) == (
        14, 12, 2
    )
    assert report["bytes_total"] == 24
    assert report["status_classes"] == {
        "2xx": 2, "3xx": 2, "4xx": 2, "5xx": 2, "other": 4,
    }
    assert report["methods"] == {"GET": 6, "POST": 6}
    assert list(report["methods"]) == ["GET", "POST"]


def test_nearest_rank_percentiles():
    report = logstats.analyze(
        _line(duration=str(value)) for value in (4.0, 1.0, 3.0, 2.0)
    )
    assert report["duration"] == {
        "count": 4, "mean": 2.5, "p50": 2.0, "p95": 4.0, "max": 4.0,
    }
    assert report["status_classes"] == {
        "2xx": 4, "3xx": 0, "4xx": 0, "5xx": 0, "other": 0,
    }
    report = logstats.analyze(_line(duration=str(value)) for value in range(1, 21))
    assert report["duration"]["p50"] == 10.0
    assert report["duration"]["p95"] == 19.0


def test_duration_rounding_and_single_value():
    report = logstats.analyze(["bad", _line(duration="0.1236")])
    assert report["duration"] == {
        "count": 1, "mean": 0.124, "p50": 0.124, "p95": 0.124, "max": 0.124,
    }
    assert logstats.analyze(["bad"])["duration"]["count"] == 0


def test_top_truncation_and_lexical_ties():
    lines = [
        _line(path=path, ip=ip)
        for path, ip in (
            ("/z", "2.0.0.1"), ("/b", "10.0.0.1"), ("/a", "1.0.0.1"),
            ("/z", "2.0.0.1"), ("/c", "3.0.0.1"),
        )
    ]
    report = logstats.analyze(lines, top=2)
    assert report["top_paths"] == [
        {"path": "/z", "count": 2}, {"path": "/a", "count": 1},
    ]
    assert report["top_ips"] == [
        {"ip": "2.0.0.1", "count": 2}, {"ip": "1.0.0.1", "count": 1},
    ]
    assert len(logstats.analyze(lines, top=20)["top_paths"]) == 4
    assert logstats.analyze(lines, top=3)["top_ips"][2]["ip"] == "10.0.0.1"


def test_cli_default_json(capsys):
    text = _line() + "\n\nbad\n" + _line(size="-") + "\n"
    assert _run(text) == 0
    output = capsys.readouterr()
    expected = logstats.analyze(text.splitlines(keepends=True))
    assert output.out == json.dumps(expected, indent=2) + "\n"
    assert output.err == ""


def test_cli_top(capsys):
    text = "\n".join(_line(path=f"/{i}", ip=f"1.1.1.{i}") for i in range(1, 8))
    assert _run(text) == 0
    report = json.loads(capsys.readouterr().out)
    assert len(report["top_paths"]) == len(report["top_ips"]) == 5
    assert _run(text, ["--top", "3", "--format", "json"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert len(report["top_paths"]) == len(report["top_ips"]) == 3


def test_cli_table(capsys):
    assert _run(_line(), ["--format", "table"]) == 0
    output = capsys.readouterr()
    assert output.err == ""
    for label in ("lines_total", "status_classes", "top_paths", "top_ips", "duration"):
        assert label in output.out
    try:
        json.loads(output.out)
    except json.JSONDecodeError:
        pass
    else:
        raise AssertionError("table output must not be JSON")


def test_cli_strict_first_error_and_physical_line_number(capsys):
    text = "\n" + _line() + "\r\n \t\nbad  \r\nsecond bad\n"
    assert _run(text, ["--strict"]) == 2
    output = capsys.readouterr()
    assert output.out == ""
    assert output.err == "malformed line 4: bad  \n"


def test_strict_stops_consuming_at_first_error(capsys):
    def lines():
        yield "bad\n"
        raise AssertionError("read beyond the first malformed line")

    with patch("builtins.open") as opened:
        opened.return_value.__enter__.return_value = lines()
        assert logstats.main(["fixture.log", "--strict"]) == 2
    assert capsys.readouterr().err == "malformed line 1: bad\n"


def test_cli_strict_valid_input(capsys):
    assert _run("\n" + _line() + "\n \t\n", ["--strict"]) == 0
    output = capsys.readouterr()
    assert json.loads(output.out)["lines_total"] == 1
    assert output.err == ""


def test_cli_missing_file(capsys):
    with patch("builtins.open", side_effect=FileNotFoundError("missing fixture.log")):
        assert logstats.main(["fixture.log"]) == 2
    output = capsys.readouterr()
    assert output.out == ""
    assert "missing fixture.log" in output.err


def test_cli_unreadable_file(capsys):
    with patch("builtins.open", side_effect=PermissionError("permission denied")):
        assert logstats.main(["fixture.log"]) == 2
    output = capsys.readouterr()
    assert output.out == ""
    assert "permission denied" in output.err


def test_cli_invalid_encoding(capsys):
    error = UnicodeDecodeError("utf-8", b"\xff", 0, 1, "invalid start byte")
    with patch("builtins.open") as opened:
        opened.return_value.__enter__.return_value.__iter__.side_effect = error
        assert logstats.main(["fixture.log"]) == 2
    output = capsys.readouterr()
    assert output.out == ""
    assert "utf-8" in output.err


def test_cli_usage_errors(capsys):
    for args in (
        ["fixture.log", "--top", "0"], ["fixture.log", "--top", "-1"],
        ["fixture.log", "--top", "abc"], ["fixture.log", "--top", "1.5"],
        ["fixture.log", "--format", "xml"], [],
    ):
        assert logstats.main(args) == 2
        output = capsys.readouterr()
        assert output.out == ""
        assert "usage:" in output.err


def test_import_has_no_side_effects():
    result = subprocess.run(
        [sys.executable, "-B", "-c", "import logstats"],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0
    assert result.stdout == result.stderr == ""
    assert {name for name in vars(logstats) if not name.startswith("_")} == {
        "parse_line", "analyze", "main",
    }
