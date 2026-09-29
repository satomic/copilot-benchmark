import datetime
import json

import logstats


def _line(
    ip="1.1.1.1",
    user="-",
    timestamp="09/Sep/2026:08:00:01 +0800",
    method="GET",
    path="/",
    status=200,
    size="1",
    duration="0.1",
):
    return (
        f'{ip} - {user} [{timestamp}] "{method} {path} HTTP/1.1" '
        f"{status} {size} {duration}"
    )


def test_parse_well_formed_line_field_by_field():
    record = logstats.parse_line(
        '203.0.113.10 - alice [09/Sep/2026:08:00:01 +0800] '
        '"GET /api/users HTTP/1.1" 200 1024 0.042\r\n'
    )

    assert record == {
        "ip": "203.0.113.10",
        "user": "alice",
        "timestamp": datetime.datetime(
            2026, 9, 9, 8, 0, 1, tzinfo=datetime.timezone(datetime.timedelta(hours=8))
        ),
        "method": "GET",
        "path": "/api/users",
        "protocol": "HTTP/1.1",
        "status": 200,
        "bytes": 1024,
        "duration": 0.042,
    }


def test_parse_malformed_line_returns_none():
    assert logstats.parse_line("this line is not a log line at all") is None
    assert logstats.parse_line(_line(ip="999.1.1.1")) is None
    assert logstats.parse_line(_line() + " trailing") is None


def test_dash_bytes_becomes_zero():
    assert logstats.parse_line(_line(size="-"))["bytes"] == 0


def test_anonymous_user_becomes_none():
    assert logstats.parse_line(_line())["user"] is None


def test_analyze_uses_nearest_rank_percentiles():
    report = logstats.analyze([_line(duration=str(value)) for value in (1, 2, 3, 4)])

    assert report["duration"] == {
        "count": 4,
        "mean": 2.5,
        "p50": 2.0,
        "p95": 4.0,
        "max": 4.0,
    }


def test_top_truncation_and_tie_breaking():
    lines = [
        _line(ip="3.3.3.3", path="/z"),
        _line(ip="2.2.2.2", path="/b"),
        _line(ip="1.1.1.1", path="/a"),
        _line(ip="2.2.2.2", path="/b"),
        _line(ip="1.1.1.1", path="/a"),
    ]

    report = logstats.analyze(lines, top=2)

    assert report["top_paths"] == [
        {"path": "/a", "count": 2},
        {"path": "/b", "count": 2},
    ]
    assert report["top_ips"] == [
        {"ip": "1.1.1.1", "count": 2},
        {"ip": "2.2.2.2", "count": 2},
    ]


def test_analyze_counts_blank_malformed_status_and_sorted_methods():
    lines = [
        "\n",
        "   \r\n",
        _line(method="POST", status=199, size="5"),
        "bad\n",
        _line(method="GET", status=600, size="7"),
        _line(method="GET", status=404, size="-"),
    ]

    report = logstats.analyze(lines)

    assert list(report) == [
        "lines_total",
        "lines_parsed",
        "lines_malformed",
        "bytes_total",
        "status_classes",
        "methods",
        "top_paths",
        "top_ips",
        "duration",
    ]
    assert report["lines_total"] == 4
    assert report["lines_parsed"] == 3
    assert report["lines_malformed"] == 1
    assert report["bytes_total"] == 12
    assert report["status_classes"] == {
        "2xx": 0,
        "3xx": 0,
        "4xx": 1,
        "5xx": 0,
        "other": 2,
    }
    assert report["methods"] == {"GET": 2, "POST": 1}


def test_empty_analysis_has_zero_duration():
    report = logstats.analyze(["", " \n"])
    assert report["duration"] == {
        "count": 0,
        "mean": 0.0,
        "p50": 0.0,
        "p95": 0.0,
        "max": 0.0,
    }


def test_strict_reports_first_malformed_line(tmp_path, capsys):
    logfile = tmp_path / "input.log"
    logfile.write_text(_line() + "\n\nbad line\n" + _line(path="/later"))

    code = logstats.main([str(logfile), "--strict"])
    output = capsys.readouterr()

    assert code == 2
    assert output.out == ""
    assert output.err == "malformed line 3: bad line\n"


def test_missing_file_exits_two(tmp_path, capsys):
    code = logstats.main([str(tmp_path / "missing.log")])
    output = capsys.readouterr()

    assert code == 2
    assert output.out == ""
    assert output.err


def test_invalid_top_is_usage_error(capsys):
    code = logstats.main(["some.log", "--top", "0"])
    output = capsys.readouterr()

    assert code == 2
    assert output.out == ""
    assert "must be at least 1" in output.err


def test_cli_json_and_table_formats(tmp_path, capsys):
    logfile = tmp_path / "input.log"
    logfile.write_text(_line())

    assert logstats.main([str(logfile)]) == 0
    json_output = capsys.readouterr()
    assert json.loads(json_output.out)["lines_parsed"] == 1
    assert json_output.out.endswith("\n")

    assert logstats.main([str(logfile), "--format", "table"]) == 0
    table_output = capsys.readouterr().out
    assert all(
        label in table_output
        for label in ("lines_total", "status_classes", "top_paths", "top_ips", "duration")
    )
    try:
        json.loads(table_output)
    except json.JSONDecodeError:
        pass
    else:
        raise AssertionError("table output must not be valid JSON")
