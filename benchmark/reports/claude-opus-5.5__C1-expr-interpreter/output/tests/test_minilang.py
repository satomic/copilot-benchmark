import os
import subprocess
import sys

import pytest

from minilang import (
    EvalError,
    LexError,
    MiniLangError,
    ParseError,
    evaluate,
    parse,
    tokenize,
)
import minilang

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def run_repl(text):
    proc = subprocess.run(
        [sys.executable, "-m", "minilang"],
        input=text,
        capture_output=True,
        text=True,
        cwd=ROOT,
        timeout=30,
    )
    return proc


# ---------------------------------------------------------------- public API

def test_public_api():
    assert sorted(minilang.__all__) == sorted(
        ["tokenize", "parse", "evaluate", "MiniLangError", "LexError", "ParseError", "EvalError"]
    )
    for cls in (LexError, ParseError, EvalError):
        assert issubclass(cls, MiniLangError)


# ---------------------------------------------------------------- lexer

def test_lex_numbers():
    toks = tokenize("123 1.5 .5 1e3 1.2e-4 2E+8")
    assert [t.kind for t in toks] == ["NUMBER"] * 6
    assert [t.value for t in toks] == [123.0, 1.5, 0.5, 1000.0, 1.2e-4, 2e8]
    assert all(isinstance(t.value, float) for t in toks)


@pytest.mark.parametrize("src", ["1.", "1.e3", "1e", "1e+", "."])
def test_lex_bad_numbers(src):
    with pytest.raises(LexError):
        tokenize(src)


def test_lex_strings_and_escapes():
    toks = tokenize(r'"a\nb\t\r\"\\"')
    assert len(toks) == 1
    assert toks[0].kind == "STRING"
    assert toks[0].value == 'a\nb\t\r"\\'


@pytest.mark.parametrize("src", ['"unterminated', '"bad \\q escape"', '"a\nb"', '"ends\\'])
def test_lex_bad_strings(src):
    with pytest.raises(LexError):
        tokenize(src)


def test_lex_kinds_and_positions():
    toks = tokenize("foo and (x_1 >= 2)")
    assert [(t.kind, t.value, t.position) for t in toks] == [
        ("IDENT", "foo", 0),
        ("KEYWORD", "and", 4),
        ("OP", "(", 8),
        ("IDENT", "x_1", 9),
        ("OP", ">=", 13),
        ("NUMBER", 2.0, 16),
        ("OP", ")", 17),
    ]


def test_lex_comments_and_whitespace():
    toks = tokenize("1 # comment\n\t+ 2 # trailing")
    assert [t.value for t in toks] == [1.0, "+", 2.0]
    assert tokenize("# only") == []


def test_lex_errors_with_position():
    with pytest.raises(LexError) as info:
        tokenize("a @ b")
    assert info.value.position == 2
    assert str(info.value) == "unexpected character: '@'"
    with pytest.raises(LexError) as info:
        tokenize("1 = 2")
    assert info.value.position == 2


# ---------------------------------------------------------------- parser

@pytest.mark.parametrize("src", ["1 < 2 < 3", "1 2", "(1", "", "# only a comment", "1 +", "f(1,", ")"])
def test_parse_errors(src):
    with pytest.raises(ParseError):
        parse(src)


def test_parse_error_position():
    with pytest.raises(ParseError) as info:
        parse("1 2")
    assert info.value.position == 2
    with pytest.raises(ParseError) as info:
        parse("1 < 2 < 3")
    assert info.value.position == 6
    with pytest.raises(ParseError) as info:
        parse("(1")
    assert info.value.position == 2


def test_parse_does_not_evaluate():
    parse("1 / 0")
    parse("undefined_fn(x)")


# ---------------------------------------------------------------- precedence

def test_precedence_additive_multiplicative():
    assert evaluate("1 + 2 * 3") == 7.0
    assert evaluate("(1 + 2) * 3") == 9.0
    assert evaluate("10 - 4 - 3") == 3.0
    assert evaluate("100 / 10 / 5") == 2.0
    assert evaluate("2 * 3 % 4") == 2.0


def test_power_right_associative():
    assert evaluate("2 ^ 3 ^ 2") == 512.0
    assert evaluate("2 * 3 ^ 2") == 18.0


def test_unary_minus_and_power():
    assert evaluate("-2 ^ 2") == -4.0
    assert evaluate("2 ^ -1") == 0.5
    assert evaluate("--3") == 3.0
    assert evaluate("-2 * 3") == -6.0


def test_comparison_vs_arithmetic_and_not():
    assert evaluate("1 + 1 == 2") is True
    assert evaluate("not 1 == 2") is True
    assert evaluate("not true and false") is False
    assert evaluate("not not true") is True


def test_and_binds_tighter_than_or():
    assert evaluate("true or false and false") is True
    assert evaluate("(true or false) and false") is False


# ---------------------------------------------------------------- evaluation

def test_arithmetic_and_modulo():
    assert evaluate("7 % 3") == 1.0
    assert evaluate("-7 % 3") == 2.0
    assert evaluate("7 % -3") == -2.0


def test_division_and_modulo_by_zero():
    with pytest.raises(EvalError, match="^division by zero$"):
        evaluate("1 / 0")
    with pytest.raises(EvalError, match="^modulo by zero$"):
        evaluate("1 % 0")


def test_power_not_real():
    with pytest.raises(EvalError):
        evaluate("(-8) ^ 0.5")


def test_string_concat_and_type_errors():
    assert evaluate('"a" + "b"') == "ab"
    for src in ('"a" + 1', "true + 1", '"a" * 2', "-true", 'not 1', '1 < "a"', "true < false"):
        with pytest.raises(EvalError):
            evaluate(src)


def test_equality_across_types():
    assert evaluate("true == 1") is False
    assert evaluate('"1" == 1') is False
    assert evaluate('"a" != "b"') is True
    assert evaluate("1 == 1.0") is True
    assert evaluate('"abc" < "abd"') is True


def test_short_circuit():
    assert evaluate("false and 1 / 0") is False
    assert evaluate("true or 1 / 0") is True
    with pytest.raises(EvalError):
        evaluate("true and 1 / 0")
    with pytest.raises(EvalError):
        evaluate("1 and true")
    with pytest.raises(EvalError):
        evaluate("true and 1")


def test_variables_and_env():
    assert evaluate("x * 2", {"x": 21.0}) == 42.0
    with pytest.raises(EvalError, match="^undefined variable: y$"):
        evaluate("y + 1")
    with pytest.raises(EvalError, match=r"^unsupported value for n: 2$"):
        evaluate("n", {"n": 2})
    with pytest.raises(EvalError):
        evaluate("n", {"n": None})


def test_env_not_mutated():
    env = {"x": 1.0, "s": "hi"}
    snapshot = dict(env)
    evaluate("x + 1", env)
    evaluate('s + "!"', env)
    assert env == snapshot


def test_undefined_function_and_no_fallback():
    with pytest.raises(EvalError, match="^undefined function: f$"):
        evaluate("f(1)")
    with pytest.raises(EvalError, match="^undefined function: x$"):
        evaluate("x(1)", {"x": 1.0})
    with pytest.raises(EvalError, match="^undefined variable: abs$"):
        evaluate("abs")


# ---------------------------------------------------------------- builtins

def test_builtin_abs_min_max():
    assert evaluate("abs(-3)") == 3.0
    assert evaluate("min(3, 1, 2)") == 1.0
    assert evaluate("max(3, 1, 2)") == 3.0
    assert evaluate("min(5)") == 5.0
    with pytest.raises(EvalError, match=r"^abs\(\) takes 1 argument\(s\), got 2$"):
        evaluate("abs(1, 2)")
    with pytest.raises(EvalError):
        evaluate("min()")
    with pytest.raises(EvalError):
        evaluate('max(1, "a")')


def test_builtin_round():
    assert evaluate("round(2.5)") == 2.0
    assert evaluate("round(3.5)") == 4.0
    assert evaluate("round(3.14159, 2)") == 3.14
    assert isinstance(evaluate("round(2.5)"), float)
    with pytest.raises(EvalError):
        evaluate("round(1.5, 0.5)")
    with pytest.raises(EvalError):
        evaluate('round("a")')


def test_builtin_strings():
    assert evaluate('len("hello")') == 5.0
    assert isinstance(evaluate('len("ab")'), float)
    assert evaluate('upper("abC")') == "ABC"
    assert evaluate('lower("AbC")') == "abc"
    with pytest.raises(EvalError):
        evaluate("len(1)")
    with pytest.raises(EvalError):
        evaluate("upper()")


def test_builtin_str_num():
    assert evaluate("str(3.0)") == "3"
    assert evaluate("str(0.5)") == "0.5"
    assert evaluate("str(true)") == "true"
    assert evaluate('str("x")') == "x"
    assert evaluate('num(" 4.5 ")') == 4.5
    assert evaluate('num("-1e2")') == -100.0
    for bad in ('num("abc")', 'num("")', "num(1)"):
        with pytest.raises(EvalError):
            evaluate(bad)


def test_builtin_if_lazy():
    assert evaluate('if(1 < 2, "yes", 1 / 0)') == "yes"
    assert evaluate('if(false, 1 / 0, "no")') == "no"
    with pytest.raises(EvalError):
        evaluate("if(1, 2, 3)")
    with pytest.raises(EvalError):
        evaluate("if(true, 1)")


def test_error_str_is_plain_message():
    try:
        evaluate("1 / 0")
    except EvalError as e:
        assert str(e) == "division by zero"


# ---------------------------------------------------------------- REPL

def test_repl_acceptance_scenario():
    proc = run_repl('x = 2\nx * 3\n:vars\n1/0\n"a\\nb"\n:quit\n')
    assert proc.returncode == 0
    assert proc.stdout.splitlines() == ["6", "x = 2", "error: division by zero", '"a\\nb"']


def test_repl_eof_blank_lines_and_formatting():
    proc = run_repl("\n   \n1.25\n0.5 * 2\ntrue\n2 ^ 3 ^ 2")
    assert proc.returncode == 0
    assert proc.stdout.splitlines() == ["1.25", "1", "true", "512"]


def test_repl_vars_sorted_and_failed_assignment():
    proc = run_repl(':vars\nb = "hi"\na = 1\nc = 1 / 0\n:vars\nc\n')
    assert proc.returncode == 0
    assert proc.stdout.splitlines() == [
        "error: division by zero",
        'a = 1',
        'b = "hi"',
        "error: undefined variable: c",
    ]


def test_repl_quit_stops_processing():
    proc = run_repl("1\n:quit\n2\n")
    assert proc.returncode == 0
    assert proc.stdout.splitlines() == ["1"]


def test_repl_parse_and_lex_errors_continue():
    proc = run_repl("1 2\n@\nx == 1\n3\n")
    assert proc.returncode == 0
    lines = proc.stdout.splitlines()
    assert len(lines) == 4
    assert all(line.startswith("error: ") for line in lines[:3])
    assert lines[3] == "3"
