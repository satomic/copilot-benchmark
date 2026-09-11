"""Hidden verification suite for task C1. Not visible to the model under test."""
import importlib
import subprocess
import sys
from pathlib import Path

import pytest

BS = chr(92)  # backslash, kept out of string literals for clarity

_IGNORED_DIRS = {"__pycache__", "_verify", ".pytest_cache", ".git", ".ruff_cache", ".mypy_cache"}


@pytest.fixture(scope="module")
def ml():
    sys.path.insert(0, ".")
    return importlib.import_module("minilang")


@pytest.fixture
def ev(ml):
    return ml.evaluate


def repl(lines: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "minilang"],
        input="\n".join(lines) + "\n",
        capture_output=True,
        text=True,
        timeout=60,
        cwd=".",
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


# ---------------------------------------------------------- package shape -----

def test_public_surface(ml):
    assert set(ml.__all__) == {
        "tokenize", "parse", "evaluate",
        "MiniLangError", "LexError", "ParseError", "EvalError",
    }
    for name in ml.__all__:
        assert hasattr(ml, name), f"missing {name}"


def test_expected_files_exist():
    for rel in (
        "minilang/__init__.py", "minilang/errors.py", "minilang/lexer.py",
        "minilang/parser.py", "minilang/evaluator.py", "minilang/builtins.py",
        "minilang/__main__.py", "tests/test_minilang.py",
    ):
        assert Path(rel).is_file(), f"missing {rel}"


def test_only_expected_files():
    expected = {
        "task.md",
        "minilang/__init__.py", "minilang/errors.py", "minilang/lexer.py",
        "minilang/parser.py", "minilang/evaluator.py", "minilang/builtins.py",
        "minilang/__main__.py", "tests/test_minilang.py",
    }
    extra = _project_files() - expected
    assert not extra, f"unexpected files created: {sorted(extra)}"


def test_error_hierarchy(ml):
    assert issubclass(ml.LexError, ml.MiniLangError)
    assert issubclass(ml.ParseError, ml.MiniLangError)
    assert issubclass(ml.EvalError, ml.MiniLangError)
    assert issubclass(ml.MiniLangError, Exception)
    for cls in (ml.LexError, ml.ParseError, ml.EvalError):
        assert not issubclass(cls, (ml.LexError, ml.ParseError, ml.EvalError)) or cls is cls


def test_no_eval_or_exec_used():
    """The interpreter must be hand-written: no eval/exec/compile, no ast module.

    Detected by walking the AST for actual calls to the builtins, not by substring
    matching. A method named `eval` on an evaluator class is perfectly legitimate
    naming — `def eval(self, node)` contains " eval(" and would trip a text scan.
    """
    import ast as _ast

    forbidden_calls = {"eval", "exec", "compile"}
    for rel in Path("minilang").glob("*.py"):
        src = rel.read_text(encoding="utf-8")
        tree = _ast.parse(src, filename=str(rel))

        # Names bound locally (def/class/assignment) shadow the builtin, so a
        # call to such a name is the model's own code, not the builtin.
        shadowed = set()
        for node in _ast.walk(tree):
            if isinstance(node, (_ast.FunctionDef, _ast.AsyncFunctionDef, _ast.ClassDef)):
                shadowed.add(node.name)
            elif isinstance(node, _ast.Assign):
                for target in node.targets:
                    if isinstance(target, _ast.Name):
                        shadowed.add(target.id)

        for node in _ast.walk(tree):
            if isinstance(node, _ast.Call) and isinstance(node.func, _ast.Name):
                name = node.func.id
                if name in forbidden_calls and name not in shadowed:
                    raise AssertionError(f"{rel}:{node.lineno} calls the builtin {name}()")
            if isinstance(node, (_ast.Import, _ast.ImportFrom)):
                module = getattr(node, "module", None) or ""
                names = [a.name for a in node.names]
                if module == "ast" or "ast" in names:
                    raise AssertionError(f"{rel}:{node.lineno} imports the ast module")


# ----------------------------------------------------------------- lexer ------

def test_token_attributes(ml):
    tokens = ml.tokenize('f(1, "s") + true and not b')
    assert tokens, "no tokens produced"
    for token in tokens:
        assert isinstance(token.kind, str)
        assert isinstance(token.position, int)
        assert hasattr(token, "value")
    assert {t.kind for t in tokens} <= {"NUMBER", "STRING", "IDENT", "KEYWORD", "OP"}
    assert "EOF" not in {t.kind for t in tokens}


def test_token_kinds_and_positions(ml):
    tokens = ml.tokenize("ab + 12")
    assert [(t.kind, t.value, t.position) for t in tokens] == [
        ("IDENT", "ab", 0), ("OP", "+", 3), ("NUMBER", 12.0, 5)
    ]


def test_keywords_are_keyword_kind(ml):
    for word in ("true", "false", "and", "or", "not"):
        (token,) = ml.tokenize(word)
        assert token.kind == "KEYWORD", f"{word} should lex as KEYWORD"


@pytest.mark.parametrize(
    "src,value",
    [
        ("123", 123.0), ("1.5", 1.5), (".5", 0.5),
        ("1e3", 1000.0), ("1.2e-4", 0.00012), ("2E+8", 2e8),
    ],
)
def test_number_forms(ml, src, value):
    (token,) = ml.tokenize(src)
    assert token.kind == "NUMBER"
    assert token.value == pytest.approx(value)


def test_string_escapes(ml):
    (token,) = ml.tokenize('"a' + BS + 'nb' + BS + 't' + BS + '"c' + BS + BS + 'd"')
    assert token.kind == "STRING"
    assert token.value == 'a\nb\t"c' + BS + "d"


def test_comments_are_skipped(ml):
    assert ml.tokenize("1 # trailing comment") == ml.tokenize("1")
    assert ml.evaluate("# leading\n2 + 3 # trailing") == 5.0


@pytest.mark.parametrize(
    "src",
    [
        '"unterminated',
        '"multi' + BS,
        "1.",
        "1 = 2",
        "a @ b",
        '"bad ' + BS + 'q escape"',
        "1 & 2",
        "$x",
        '"newline' + "\n" + 'inside"',
        "!",
    ],
)
def test_lex_errors(ml, src):
    with pytest.raises(ml.LexError):
        ml.tokenize(src)


def test_lex_error_has_position(ml):
    with pytest.raises(ml.LexError) as ei:
        ml.tokenize("1 + @")
    assert isinstance(ei.value.position, int)
    assert ei.value.position == 4


# ---------------------------------------------------------------- parser ------

def test_parse_does_not_evaluate(ml):
    ml.parse("1 / 0")
    ml.parse("undefined_name + 1")
    ml.parse("nope(1)")


@pytest.mark.parametrize(
    "src", ["1 < 2 < 3", "1 == 2 != 3", "1 2", "(1", "1 +", "", "   ", "# only a comment",
            "f(", "f(1,", "()", "and 1", "* 2", "1 ,", ")"]
)
def test_parse_errors(ml, src):
    with pytest.raises(ml.ParseError):
        ml.parse(src)


def test_parse_error_has_position(ml):
    with pytest.raises(ml.ParseError) as ei:
        ml.parse("1 2")
    assert ei.value.position == 2


def test_str_of_error_is_plain_message(ml):
    with pytest.raises(ml.EvalError) as ei:
        ml.evaluate("1 / 0")
    assert str(ei.value) == "division by zero"


# ------------------------------------------------------------ precedence ------

@pytest.mark.parametrize(
    "src,expected",
    [
        ("1 + 2 * 3", 7.0),
        ("(1 + 2) * 3", 9.0),
        ("2 * 3 + 4 * 5", 26.0),
        ("10 - 2 - 3", 5.0),                  # left-assoc
        ("100 / 5 / 2", 10.0),                # left-assoc
        ("2 ^ 3 ^ 2", 512.0),                 # right-assoc
        ("-2 ^ 2", -4.0),                     # unary looser than ^
        ("2 ^ -1", 0.5),
        ("-(2 ^ 2)", -4.0),
        ("(-2) ^ 2", 4.0),
        ("- - 3", 3.0),
        ("7 % 3", 1.0),
        ("-7 % 3", 2.0),                      # Python sign rules
        ("7 % -3", -2.0),
        ("2 + 3 == 5", True),                 # additive tighter than comparison
        ("1 < 2 and 3 < 4", True),            # comparison tighter than and
        ("true or false and false", True),    # and tighter than or
        ("not 1 == 2", True),                 # not looser than comparison
        ("not true and true", False),         # not binds tighter than and
        ("1 + 2 < 4 or false", True),
    ],
)
def test_precedence_and_associativity(ev, src, expected):
    got = ev(src)
    assert got == expected and type(got) is type(expected), f"{src} -> {got!r}"


def test_all_numbers_are_floats(ev):
    for src in ("1", "1 + 1", 'len("ab")', "abs(-3)", "min(1, 2)", "round(1.4)"):
        assert isinstance(ev(src), float), f"{src} must yield a float"
        assert not isinstance(ev(src), bool)


# ------------------------------------------------------------- semantics ------

@pytest.mark.parametrize(
    "src,expected",
    [
        ('"a" + "b"', "ab"),
        ('"" + "x"', "x"),
        ("true == true", True),
        ("true == 1", False),                # different types are never equal
        ('1 == "1"', False),
        ("true != 1", True),
        ('"a" < "b"', True),
        ('"abc" >= "abd"', False),
        ("1 <= 1", True),
        ("false and true", False),
        ("true and false", False),
        ("false or true", True),
        ("not false", True),
    ],
)
def test_operator_semantics(ev, src, expected):
    got = ev(src)
    assert got == expected and type(got) is type(expected), f"{src} -> {got!r}"


def test_short_circuit(ev):
    assert ev("false and 1 / 0") is False
    assert ev("true or 1 / 0") is True
    assert ev("false and undefined_thing") is False
    assert ev("true or undefined_thing") is True


def test_short_circuit_still_type_checks_left(ml):
    with pytest.raises(ml.EvalError):
        ml.evaluate('"s" and true')
    with pytest.raises(ml.EvalError):
        ml.evaluate("1 or true")


def test_lazy_if(ev):
    assert ev('if(1 < 2, "yes", 1 / 0)') == "yes"
    assert ev('if(2 < 1, 1 / 0, "no")') == "no"
    assert ev("if(true, 1, undefined_thing)") == 1.0


@pytest.mark.parametrize(
    "src,message",
    [
        ("1 / 0", "division by zero"),
        ("1 % 0", "modulo by zero"),
        ("x", "undefined variable: x"),
        ("nope(1)", "undefined function: nope"),
    ],
)
def test_exact_error_messages(ml, src, message):
    with pytest.raises(ml.EvalError) as ei:
        ml.evaluate(src)
    assert str(ei.value) == message


@pytest.mark.parametrize(
    "src",
    [
        '1 + "a"', '"a" + 1', "true + true", '1 - "a"', 'true * 2',
        '"a" < 1', "true < false", "1 and true", "not 1", '-"a"', "-true",
        "(-8) ^ 0.5",
    ],
)
def test_type_errors(ml, src):
    with pytest.raises(ml.EvalError):
        ml.evaluate(src)


def test_variable_lookup(ev):
    assert ev("x * 2", {"x": 21.0}) == 42.0
    assert ev("a + b", {"a": 1.0, "b": 2.0}) == 3.0
    assert ev("s + s", {"s": "ab"}) == "abab"
    assert ev("flag", {"flag": True}) is True


def test_env_is_not_mutated(ev):
    env = {"x": 1.0}
    ev("x + 1", env)
    assert env == {"x": 1.0}


def test_env_rejects_unsupported_values(ml):
    with pytest.raises(ml.EvalError) as ei:
        ml.evaluate("x", {"x": 2})          # int, not float
    assert str(ei.value) == "unsupported value for x: 2"
    with pytest.raises(ml.EvalError):
        ml.evaluate("x", {"x": [1]})
    with pytest.raises(ml.EvalError):
        ml.evaluate("x", {"x": None})


def test_function_and_variable_namespaces_are_separate(ml):
    # a variable named like a call target must not become callable
    with pytest.raises(ml.EvalError) as ei:
        ml.evaluate("f(1)", {"f": 2.0})
    assert str(ei.value) == "undefined function: f"
    # a builtin name used as a bare variable is not defined
    with pytest.raises(ml.EvalError) as ei:
        ml.evaluate("abs")
    assert str(ei.value) == "undefined variable: abs"


# -------------------------------------------------------------- builtins ------

@pytest.mark.parametrize(
    "src,expected",
    [
        ("abs(-3)", 3.0), ("abs(3)", 3.0),
        ("min(3, 1, 2)", 1.0), ("min(5)", 5.0),
        ("max(3, 1, 2)", 3.0), ("max(-1)", -1.0),
        ("round(1.4)", 1.0), ("round(1.6)", 2.0),
        ("round(1.2345, 2)", 1.23),
        ('len("hello")', 5.0), ('len("")', 0.0),
        ('upper("aB")', "AB"), ('lower("aB")', "ab"),
        ("str(3.0)", "3"), ("str(0.5)", "0.5"), ("str(true)", "true"),
        ('str("x")', "x"),
        ('num("4.5")', 4.5), ('num(" 4.5 ")', 4.5), ('num("-2")', -2.0),
        ('if(true, "a", "b")', "a"), ('if(false, "a", "b")', "b"),
    ],
)
def test_builtins(ev, src, expected):
    got = ev(src)
    assert got == pytest.approx(expected) if isinstance(expected, float) else got == expected
    assert type(got) is type(expected), f"{src} -> {type(got).__name__}"


def test_builtin_arity_message(ml):
    with pytest.raises(ml.EvalError) as ei:
        ml.evaluate("abs(1, 2)")
    assert str(ei.value) == "abs() takes 1 argument(s), got 2"


@pytest.mark.parametrize(
    "src",
    [
        "abs()", "abs(1, 2)", "len()", 'len(1)', "upper(1)", "lower(1)",
        'num("abc")', 'num(1)', "round()", "round(1, 1.5)", "min()", "max()",
        'min(1, "a")', 'if(1, 2, 3)', "if(true, 1)", "if(true, 1, 2, 3)",
    ],
)
def test_builtin_errors(ml, src):
    with pytest.raises(ml.EvalError):
        ml.evaluate(src)


def test_nested_calls(ev):
    assert ev('len(upper("abc"))') == 3.0
    assert ev("max(min(5, 3), abs(-2))") == 3.0
    assert ev('num(str(2.5)) + 1') == 3.5
    assert ev('if(len("ab") == 2, max(1, 2), 0)') == 2.0


# ------------------------------------------------------------------ REPL ------

def test_repl_reference_session():
    p = repl(["x = 2", "x * 3", ":vars", "1/0", '"a' + BS + 'nb"', ":quit"])
    assert p.returncode == 0, p.stderr
    assert p.stdout.splitlines() == [
        "6",
        "x = 2",
        "error: division by zero",
        '"a' + BS + 'nb"',
    ]


def test_repl_ignores_blank_lines_and_exits_on_eof():
    p = repl(["", "   ", "1 + 1", ""])
    assert p.returncode == 0, p.stderr
    assert p.stdout.splitlines() == ["2"]


def test_repl_vars_sorted_and_empty():
    p = repl([":vars", "b = 2", "a = 1", ":vars"])
    assert p.returncode == 0, p.stderr
    assert p.stdout.splitlines() == ["a = 1", "b = 2"]


def test_repl_error_leaves_env_unchanged():
    p = repl(["x = 1", "y = 1 / 0", ":vars"])
    assert p.returncode == 0, p.stderr
    assert p.stdout.splitlines() == ["error: division by zero", "x = 1"]


def test_repl_assignment_can_reference_existing_vars():
    p = repl(["a = 2", "b = a * 3", "b"])
    assert p.stdout.splitlines() == ["6"]


def test_repl_equality_is_not_assignment():
    p = repl(["x = 1", "x == 1"])
    assert p.stdout.splitlines() == ["true"]


def test_repl_number_formatting():
    p = repl(["3.0", "0.5", "-4.0", "2 ^ 10", "1 / 4"])
    assert p.stdout.splitlines() == ["3", "0.5", "-4", "1024", "0.25"]


def test_repl_boolean_and_string_formatting():
    p = repl(["true", "false", '"hi"', '"tab' + BS + 'there"'])
    assert p.stdout.splitlines() == [
        "true", "false", '"hi"', '"tab' + BS + 'there"'
    ]


def test_repl_quit_stops_processing():
    p = repl([":quit", "1 + 1"])
    assert p.returncode == 0
    assert p.stdout == ""


def test_repl_lex_and_parse_errors_are_reported():
    p = repl(["1 @ 2", "1 < 2 < 3", "1 + 1"])
    assert p.returncode == 0, p.stderr
    lines = p.stdout.splitlines()
    assert len(lines) == 3
    assert lines[0].startswith("error: ")
    assert lines[1].startswith("error: ")
    assert lines[2] == "2"


# ------------------------------------------------- model's own test suite -----

def test_model_test_suite_is_substantial():
    src = Path("tests/test_minilang.py").read_text(encoding="utf-8")
    count = len([m for m in src.splitlines() if m.strip().startswith("def test_")])
    assert count >= 25, f"expected >= 25 test functions, found {count}"
    assert "subprocess" in src, "REPL must be exercised through subprocess"
