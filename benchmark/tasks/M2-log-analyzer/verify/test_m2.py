"""Hidden verification suite for task M2. Not visible to the model under test."""
import hashlib
import importlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

def _public_names(module) -> set[str]:
    """Public names *defined* by `module`, excluding imported modules and objects."""
    import types

    names = set()
    for name, value in vars(module).items():
        if name.startswith("_"):
            continue
        if isinstance(value, types.ModuleType):
            continue
        if getattr(value, "__module__", module.__name__) != module.__name__:
            continue
        names.add(name)
    return names


def _sealed_digest(relpath: str) -> str | None:
    """Expected sha256 for a pristine seed file, from _seal.json next to this test.

    The grader writes _seal.json when it copies this suite in. Returns None when
    no seal is available (the check then skips).
    """
    import json
    from pathlib import Path as _P

    seal = _P(__file__).with_name("_seal.json")
    if not seal.is_file():
        return None
    try:
        return json.loads(seal.read_text(encoding="utf-8")).get(relpath)
    except (OSError, ValueError):
        return None


SCRIPT = "logstats.py"

GOOD = '203.0.113.10 - - [09/Sep/2026:08:00:01 +0800] "GET /api/users HTTP/1.1" 200 1024 0.042'

_IGNORED_DIRS = {"__pycache__", "_verify", ".pytest_cache", ".git", ".ruff_cache", ".mypy_cache"}


@pytest.fixture(scope="module")
def mod():
    sys.path.insert(0, ".")
    return importlib.import_module("logstats")


def run_cli(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, SCRIPT, *args], capture_output=True, text=True, timeout=60
    )


def _project_files() -> set[str]:
    out = set()
    for p in Path(".").rglob("*"):
        if not p.is_file() or p.suffix == ".pyc":
            continue
        if any(part in _IGNORED_DIRS for part in p.parts):
            continue
        out.add(p.as_posix())
    return out


def line(
    ip="1.1.1.1", user="-", ts="09/Sep/2026:08:00:01 +0800",
    method="GET", path="/a", proto="HTTP/1.1", status=200, size=1, dur=0.5,
) -> str:
    return f'{ip} - {user} [{ts}] "{method} {path} {proto}" {status} {size} {dur}'


# ------------------------------------------------------------- parse_line -----

def test_parse_good_line(mod):
    rec = mod.parse_line(GOOD)
    assert rec["ip"] == "203.0.113.10"
    assert rec["user"] is None
    assert rec["method"] == "GET"
    assert rec["path"] == "/api/users"
    assert rec["protocol"] == "HTTP/1.1"
    assert rec["status"] == 200
    assert rec["bytes"] == 1024
    assert rec["duration"] == 0.042
    assert rec["timestamp"].utcoffset().total_seconds() == 8 * 3600
    assert (rec["timestamp"].year, rec["timestamp"].month, rec["timestamp"].day) == (2026, 9, 9)
    assert rec["timestamp"].hour == 8


def test_parse_line_key_set(mod):
    assert set(mod.parse_line(GOOD)) == {
        "ip", "user", "timestamp", "method", "path",
        "protocol", "status", "bytes", "duration",
    }


def test_named_user_and_dash_bytes(mod):
    rec = mod.parse_line(
        '198.51.100.7 - alice [09/Sep/2026:08:00:03 +0800] "GET / HTTP/1.1" 304 - 0.011'
    )
    assert rec["user"] == "alice"
    assert rec["bytes"] == 0


def test_parse_line_accepts_trailing_newline(mod):
    assert mod.parse_line(GOOD + "\n") is not None
    assert mod.parse_line(GOOD + "\r\n") is not None


@pytest.mark.parametrize(
    "bad",
    [
        "this line is not a log line at all",
        '"GET /orphan HTTP/1.1" 200 100 0.010',
        '1.1.1.1 - - [09/Sep/2026:08:00:01 BAD] "GET /a HTTP/1.1" 200 1 0.5',
        '1.1.1.1 - - [09/Sep/2026:08:00:01 +0800] "GET /a HTTP/1.1" 200 1 abc',
        '1.1.1.1 - - [09/Sep/2026:08:00:01 +0800] "GET /a HTTP/1.1" 20 1 0.5',
        '1.1.1.1 - - [09/Sep/2026:08:00:01 +0800] "get /a HTTP/1.1" 200 1 0.5',
        '1.1.1.1 - - [09/Sep/2026:08:00:01 +0800] GET /a HTTP/1.1 200 1 0.5',
        '1.1.1.1 - - [32/Xxx/2026:08:00:01 +0800] "GET /a HTTP/1.1" 200 1 0.5',
        "",
        "   ",
    ],
)
def test_malformed_lines_return_none(mod, bad):
    assert mod.parse_line(bad) is None


# ---------------------------------------------------------------- analyze -----

def test_analyze_empty(mod):
    r = mod.analyze([])
    assert r["lines_total"] == 0
    assert r["lines_parsed"] == 0
    assert r["lines_malformed"] == 0
    assert r["bytes_total"] == 0
    assert r["status_classes"] == {"2xx": 0, "3xx": 0, "4xx": 0, "5xx": 0, "other": 0}
    assert r["methods"] == {}
    assert r["top_paths"] == [] and r["top_ips"] == []
    assert r["duration"] == {"count": 0, "mean": 0.0, "p50": 0.0, "p95": 0.0, "max": 0.0}


def test_analyze_report_key_order(mod):
    assert list(mod.analyze([])) == [
        "lines_total", "lines_parsed", "lines_malformed", "bytes_total",
        "status_classes", "methods", "top_paths", "top_ips", "duration",
    ]


def test_blank_lines_are_ignored_entirely(mod):
    r = mod.analyze([line(), "", "   ", "\n", line()])
    assert (r["lines_total"], r["lines_parsed"], r["lines_malformed"]) == (2, 2, 0)


def test_malformed_counted_not_fatal(mod):
    r = mod.analyze([line(), "garbage", line()])
    assert (r["lines_total"], r["lines_parsed"], r["lines_malformed"]) == (3, 2, 1)


def test_nearest_rank_percentiles(mod):
    r = mod.analyze([line(dur=d) for d in (1.0, 2.0, 3.0, 4.0)])
    assert r["duration"]["p50"] == 2.0
    assert r["duration"]["p95"] == 4.0
    assert r["duration"]["max"] == 4.0
    assert r["duration"]["mean"] == 2.5
    assert r["duration"]["count"] == 4


def test_percentile_single_value(mod):
    r = mod.analyze([line(dur=0.25)])
    assert r["duration"]["p50"] == 0.25
    assert r["duration"]["p95"] == 0.25


def test_percentile_n_20(mod):
    # n=20: p95 index = ceil(0.95*20)-1 = 18 -> the 19th smallest
    r = mod.analyze([line(dur=float(i)) for i in range(1, 21)])
    assert r["duration"]["p95"] == 19.0
    assert r["duration"]["p50"] == 10.0


def test_status_classes(mod):
    r = mod.analyze([
        line(status=200), line(status=299), line(status=301), line(status=404),
        line(status=500), line(status=599), line(status=100), line(status=600),
    ])
    assert r["status_classes"] == {"2xx": 2, "3xx": 1, "4xx": 1, "5xx": 2, "other": 2}


def test_bytes_total_treats_dash_as_zero(mod):
    r = mod.analyze([line(size=10), line(size="-"), line(size=5)])
    assert r["bytes_total"] == 15


def test_methods_sorted(mod):
    r = mod.analyze([line(method=m) for m in ("POST", "GET", "DELETE", "GET")])
    assert list(r["methods"].items()) == [("DELETE", 1), ("GET", 2), ("POST", 1)]


def test_top_truncation_and_tie_break(mod):
    rows = (
        [line(path="/b")] * 3
        + [line(path="/a")] * 3
        + [line(path="/c")] * 2
        + [line(path="/d")] * 1
    )
    r = mod.analyze(rows, top=2)
    assert r["top_paths"] == [{"path": "/a", "count": 3}, {"path": "/b", "count": 3}]


def test_top_ips_tie_break(mod):
    rows = [line(ip="10.0.0.2")] * 2 + [line(ip="10.0.0.1")] * 2 + [line(ip="10.0.0.3")]
    r = mod.analyze(rows, top=3)
    assert [row["ip"] for row in r["top_ips"]] == ["10.0.0.1", "10.0.0.2", "10.0.0.3"]


def test_top_default_is_five(mod):
    rows = [line(path=f"/p{i}") for i in range(9)]
    assert len(mod.analyze(rows)["top_paths"]) == 5


def test_analyze_accepts_a_generator(mod):
    r = mod.analyze(iter([line(), line()]))
    assert r["lines_parsed"] == 2


# -------------------------------------------------------------------- CLI -----

def test_cli_sample_log_json():
    p = run_cli("access.log", "--top", "3")
    assert p.returncode == 0, p.stderr
    report = json.loads(p.stdout)
    assert report["lines_total"] == 40
    assert report["lines_parsed"] == 36
    assert report["lines_malformed"] == 4
    assert report["bytes_total"] == 156534
    assert report["status_classes"] == {"2xx": 26, "3xx": 2, "4xx": 5, "5xx": 3, "other": 0}
    assert report["methods"] == {
        "DELETE": 1, "GET": 27, "HEAD": 1, "PATCH": 1, "POST": 5, "PUT": 1
    }
    assert report["top_paths"] == [
        {"path": "/api/orders", "count": 8},
        {"path": "/api/users", "count": 8},
        {"path": "/", "count": 7},
    ]
    assert report["top_ips"] == [
        {"ip": "203.0.113.10", "count": 12},
        {"ip": "198.51.100.7", "count": 10},
        {"ip": "192.0.2.44", "count": 8},
    ]
    assert report["duration"] == {
        "count": 36, "mean": 0.26, "p50": 0.067, "p95": 2.4, "max": 3.011
    }


def test_cli_json_is_indented_two_and_ends_with_newline():
    p = run_cli("access.log")
    assert p.returncode == 0
    assert p.stdout.endswith("}\n")
    assert p.stdout.count("\n") > 20
    assert '\n  "lines_total"' in p.stdout


def test_cli_table_format():
    p = run_cli("access.log", "--format", "table")
    assert p.returncode == 0, p.stderr
    for token in ("lines_total", "status_classes", "top_paths", "top_ips", "duration"):
        assert token in p.stdout, f"table output missing {token!r}"
    with pytest.raises(json.JSONDecodeError):
        json.loads(p.stdout)


def test_cli_strict_exits_2():
    p = run_cli("access.log", "--strict")
    assert p.returncode == 2
    assert p.stdout == ""
    assert "malformed line 5:" in p.stderr


def test_cli_strict_clean_file_exits_0(tmp_path):
    clean = tmp_path / "clean.log"
    clean.write_text(line() + "\n" + line(path="/b") + "\n", encoding="utf-8")
    p = run_cli(str(clean), "--strict")
    assert p.returncode == 0, p.stderr
    assert json.loads(p.stdout)["lines_parsed"] == 2


def test_cli_missing_file_exits_2():
    p = run_cli("definitely-not-here.log")
    assert p.returncode == 2
    assert p.stdout == ""
    assert p.stderr.strip() != ""


@pytest.mark.parametrize("bad", ["0", "-3", "abc", ""])
def test_cli_bad_top_exits_2(bad):
    p = run_cli("access.log", "--top", bad)
    assert p.returncode == 2, f"--top {bad!r} should be a usage error"
    assert p.stdout == ""


def test_cli_no_args_exits_2():
    p = run_cli()
    assert p.returncode == 2


# ---------------------------------------------------------------- hygiene -----

def test_access_log_unmodified():
    expected = _sealed_digest("access.log")
    if expected is None:
        pytest.fail("no _seal.json found — the grader must seal seed files before running")
    actual = hashlib.sha256(Path("access.log").read_bytes()).hexdigest()
    assert actual == expected, "access.log was modified"


def test_import_is_silent(tmp_path):
    probe = tmp_path / "probe.py"
    probe.write_text("import sys; sys.path.insert(0, '.'); import logstats\n", encoding="utf-8")
    p = subprocess.run(
        [sys.executable, str(probe)], capture_output=True, text=True, timeout=60, cwd="."
    )
    assert p.returncode == 0
    assert p.stdout == "" and p.stderr == ""


def test_no_extra_public_names(mod):
    public = _public_names(mod)
    assert public == {"parse_line", "analyze", "main"}, (
        f"public names must be exactly parse_line/analyze/main, got {sorted(public)}"
    )


def test_only_expected_files():
    expected = {"task.md", "access.log", "logstats.py", "tests/test_logstats.py"}
    extra = _project_files() - expected
    assert not extra, f"unexpected files created: {sorted(extra)}"


def test_model_test_suite_is_substantial():
    src = Path("tests/test_logstats.py").read_text(encoding="utf-8")
    count = len([m for m in src.splitlines() if m.strip().startswith("def test_")])
    assert count >= 8, f"expected >= 8 test functions, found {count}"
