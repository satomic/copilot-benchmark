"""Hidden verification suite for task A5. Not visible to the model under test."""
import importlib
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


SCRIPT = "wordfreq.py"


@pytest.fixture(scope="module")
def mod():
    sys.path.insert(0, ".")
    return importlib.import_module("wordfreq")


def run_cli(stdin: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, SCRIPT, *args],
        input=stdin,
        capture_output=True,
        text=True,
        timeout=30,
    )


# ---------------------------------------------------------------- tokenize ----

@pytest.mark.parametrize(
    "text,expected",
    [
        ("Hello, world! Hello.", ["hello", "world", "hello"]),
        ("", []),
        ("   \n\t ", []),
        ("'''", []),
        ("'quoted'", ["quoted"]),
        ("''a''", ["a"]),
        ("don't stop rock'n'roll", ["don't", "stop", "rock'n'roll"]),
        ("a-b", ["a", "b"]),
        ("x1 2y", ["x1", "2y"]),
        ("MiXeD CaSe", ["mixed", "case"]),
        ("über café", ["ber", "caf"]),          # non-ASCII letters are separators
        ("a.b,c;d", ["a", "b", "c", "d"]),
        ("__x__", ["x"]),                        # underscore is not a word character here
        ("100 200 100", ["100", "200", "100"]),
    ],
)
def test_tokenize(mod, text, expected):
    assert mod.tokenize(text) == expected


# -------------------------------------------------------------- top_words ----

@pytest.mark.parametrize(
    "text,n,expected",
    [
        ("b b a a c", 2, [("a", 2), ("b", 2)]),
        ("b b a a c", 3, [("a", 2), ("b", 2), ("c", 1)]),
        ("z z z y", 10, [("z", 3), ("y", 1)]),
        ("", 5, []),
        ("'''", 5, []),
        ("one", 1, [("one", 1)]),
        ("B b A a", 2, [("a", 2), ("b", 2)]),
        ("d c b a", 4, [("a", 1), ("b", 1), ("c", 1), ("d", 1)]),
        ("aa a aa a b", 2, [("a", 2), ("aa", 2)]),
    ],
)
def test_top_words(mod, text, n, expected):
    assert mod.top_words(text, n) == expected


def test_top_words_default_is_ten(mod):
    text = " ".join(f"w{i} " * (30 - i) for i in range(15))
    assert len(mod.top_words(text)) == 10


@pytest.mark.parametrize("n", [0, -1, -100])
def test_top_words_rejects_non_positive_n(mod, n):
    with pytest.raises(ValueError):
        mod.top_words("a b c", n)


def test_top_words_returns_tuples(mod):
    out = mod.top_words("a a b", 2)
    assert all(isinstance(item, tuple) and len(item) == 2 for item in out)
    assert all(isinstance(w, str) and isinstance(c, int) for w, c in out)


# --------------------------------------------------------------------- CLI ----

def test_cli_basic():
    p = run_cli("b b a a c", "-n", "2")
    assert p.returncode == 0
    assert p.stdout == "a\t2\nb\t2\n"


def test_cli_top_alias():
    p = run_cli("b b a a c", "--top", "2")
    assert p.returncode == 0
    assert p.stdout == "a\t2\nb\t2\n"


def test_cli_default_top_ten():
    text = " ".join(f"w{i:02d} " * (30 - i) for i in range(15))
    p = run_cli(text)
    assert p.returncode == 0
    assert len(p.stdout.strip().splitlines()) == 10


def test_cli_empty_input():
    p = run_cli("")
    assert p.returncode == 0
    assert p.stdout == ""


def test_cli_only_punctuation():
    p = run_cli("!!! ... ???")
    assert p.returncode == 0
    assert p.stdout == ""


def test_cli_reads_stdin_not_argv():
    p = run_cli("a a b", "-n", "1")
    assert p.returncode == 0
    assert p.stdout == "a\t2\n"


@pytest.mark.parametrize("bad", ["0", "-1", "abc", "1.5", ""])
def test_cli_usage_errors_exit_2(bad):
    p = run_cli("x y z", "-n", bad)
    assert p.returncode == 2, f"expected exit 2 for -n {bad!r}, got {p.returncode}"
    assert p.stdout == "", f"stdout must be empty on usage error, got {p.stdout!r}"
    assert p.stderr.strip() != "", "a usage message must be written to stderr"


def test_cli_output_has_no_extra_lines():
    p = run_cli("a a a b b c")
    assert p.returncode == 0
    lines = p.stdout.split("\n")
    assert lines[-1] == ""              # exactly one trailing newline
    assert "" not in lines[:-1]         # no blank lines in between
    for line in lines[:-1]:
        assert line.count("\t") == 1


# ------------------------------------------------------------- hygiene -------

def test_import_is_silent(tmp_path):
    probe = tmp_path / "probe.py"
    probe.write_text(
        "import sys; sys.path.insert(0, '.'); import wordfreq\n", encoding="utf-8"
    )
    p = subprocess.run(
        [sys.executable, str(probe)], capture_output=True, text=True, timeout=30, cwd="."
    )
    assert p.returncode == 0
    assert p.stdout == ""
    assert p.stderr == ""


def test_no_extra_public_names(mod):
    public = _public_names(mod)
    assert public == {"tokenize", "top_words", "main"}, (
        f"public names must be exactly tokenize/top_words/main, got {sorted(public)}"
    )


def test_only_expected_file_created():
    created = {p.name for p in Path(".").iterdir() if p.is_file()}
    created -= {"task.md", "wordfreq.py"}
    assert not created, f"unexpected files created: {sorted(created)}"
