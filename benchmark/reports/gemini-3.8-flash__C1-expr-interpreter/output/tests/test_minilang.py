"""Comprehensive test suite for minilang."""

import subprocess
import sys
from pathlib import Path
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

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_acceptance_criteria_eval():
    assert evaluate("1 + 2 * 3") == 7.0
    assert evaluate("(1 + 2) * 3") == 9.0
    assert evaluate("2 ^ 3 ^ 2") == 512.0
    assert evaluate("-2 ^ 2") == -4.0
    assert evaluate("2 ^ -1") == 0.5
    assert evaluate("7 % 3") == 1.0
    assert evaluate("-7 % 3") == 2.0
    assert evaluate('"a" + "b"') == "ab"
    assert evaluate("not 1 == 2") is True
    assert evaluate("true == 1") is False
    assert evaluate("false and 1 / 0") is False
    assert evaluate("true or 1 / 0") is True
    assert evaluate('if(1 < 2, "yes", 1 / 0)') == "yes"
    assert evaluate("x * 2", {"x": 21.0}) == 42.0
    assert evaluate('len("hello")') == 5.0
    assert evaluate("min(3, 1, 2)") == 1.0
    assert evaluate("str(3.0)") == "3"
    assert evaluate('num(" 4.5 ")') == 4.5
    assert evaluate("# just a comment\n1 + 1") == 2.0


def test_acceptance_criteria_parse_errors():
    parse("1 / 0")  # parsing must not evaluate

    for src in ("1 < 2 < 3", "1 2", "(1", "", "# only a comment"):
        with pytest.raises(ParseError) as exc_info:
            parse(src)
        assert exc_info.value.position is not None


def test_acceptance_criteria_lex_errors():
    for src in ('"unterminated', "1.", "1 = 2", "a @ b", '"bad \\q escape"'):
        with pytest.raises(LexError) as exc_info:
            tokenize(src)
        assert exc_info.value.position is not None


def test_number_lexing():
    for src, expected in [
        ("123", 123.0),
        ("1.5", 1.5),
        (".5", 0.5),
        ("1e3", 1000.0),
        ("1.2e-4", 0.00012),
        ("2E+8", 200000000.0),
    ]:
        toks = tokenize(src)
        assert len(toks) == 1
        assert toks[0].kind == "NUMBER"
        assert toks[0].value == expected

    # Invalid numbers
    for bad in ("1.", "1.e3", "1e", "1e+", "1a"):
        with pytest.raises(LexError):
            tokenize(bad)


def test_string_lexing_and_escapes():
    toks = tokenize(r'"hello\nworld\t\"\\ \r"')
    assert len(toks) == 1
    assert toks[0].kind == "STRING"
    assert toks[0].value == 'hello\nworld\t"\\ \r'

    # Empty string
    toks_empty = tokenize('""')
    assert len(toks_empty) == 1
    assert toks_empty[0].value == ""

    # Unterminated string
    with pytest.raises(LexError):
        tokenize('"no close')

    # Literal newline in string
    with pytest.raises(LexError):
        tokenize('"line1\nline2"')


def test_comments_and_whitespace():
    toks = tokenize("  # first line comment\n  42 # inline comment\n")
    assert len(toks) == 1
    assert toks[0].kind == "NUMBER"
    assert toks[0].value == 42.0

    # Comment only is empty tokens
    assert tokenize("# full comment\n# second comment") == []


def test_tokens_attributes_and_kinds():
    toks = tokenize('x + 10 == true "hi"')
    expected_kinds = ["IDENT", "OP", "NUMBER", "OP", "KEYWORD", "STRING"]
    assert [t.kind for t in toks] == expected_kinds
    for t in toks:
        assert hasattr(t, "kind")
        assert hasattr(t, "value")
        assert hasattr(t, "position")
        assert isinstance(t.position, int)


def test_precedence_or_and():
    # 'and' binds tighter than 'or'
    assert evaluate("true or false and false") is True
    assert evaluate("false and false or true") is True
    assert evaluate("false or false or true") is True


def test_precedence_not_and_comparison():
    # 'not' binds looser than comparison: not a == b -> not (a == b)
    assert evaluate("not 1 == 2") is True
    assert evaluate("not 2 == 2") is False
    assert evaluate("not 1 < 2") is False
    assert evaluate("not not true") is True


def test_precedence_comparison_and_additive():
    assert evaluate("1 + 2 < 2 + 2") is True
    assert evaluate("3 * 2 == 1 + 5") is True


def test_precedence_additive_and_multiplicative():
    assert evaluate("1 + 2 * 3") == 7.0
    assert evaluate("2 * 3 + 4") == 10.0
    assert evaluate("10 - 4 / 2") == 8.0
    assert evaluate("10 % 3 * 2") == 2.0


def test_precedence_multiplicative_and_unary():
    assert evaluate("2 * -3") == -6.0
    assert evaluate("-4 * -2") == 8.0
    assert evaluate("-10 / 2") == -5.0


def test_power_precedence_and_associativity():
    # right-associative: 2 ^ 3 ^ 2 is 2 ^ (3 ^ 2) = 512
    assert evaluate("2 ^ 3 ^ 2") == 512.0
    assert evaluate("2 ^ 2 ^ 3") == 256.0


def test_power_unary_minus():
    # Unary minus binds looser than ^: -2 ^ 2 == -(2 ^ 2) == -4
    assert evaluate("-2 ^ 2") == -4.0
    assert evaluate("(-2) ^ 2") == 4.0
    assert evaluate("2 ^ -1") == 0.5
    assert evaluate("2 ^ -2") == 0.25


def test_power_complex_or_negative_zero():
    # Result not a real number raises EvalError
    with pytest.raises(EvalError):
        evaluate("(-8) ^ 0.5")

    # Division by zero through negative power
    with pytest.raises(EvalError) as exc_info:
        evaluate("0 ^ -1")
    assert "division by zero" in str(exc_info.value)


def test_non_associative_comparison():
    for expr in ("1 < 2 < 3", "1 == 2 == 3", "1 < 2 == 3", "2 >= 1 > 0"):
        with pytest.raises(ParseError):
            parse(expr)


def test_comparison_types_and_operators():
    assert evaluate("1 < 2") is True
    assert evaluate("2 <= 2") is True
    assert evaluate("3 > 2") is True
    assert evaluate("3 >= 3") is True
    assert evaluate('"apple" < "banana"') is True
    assert evaluate('"b" >= "a"') is True

    # Type mismatch on ordered comparison is EvalError
    with pytest.raises(EvalError):
        evaluate('1 < "2"')
    with pytest.raises(EvalError):
        evaluate("true < false")


def test_equality_different_types():
    # Values of different types are never equal and never error
    assert evaluate("true == 1") is False
    assert evaluate("false == 0") is False
    assert evaluate('1 == "1"') is False
    assert evaluate('true != "true"') is True
    assert evaluate("1 != true") is True


def test_short_circuit_and():
    # Left is false, right is not evaluated
    assert evaluate("false and (1 / 0)") is False
    assert evaluate("false and undefined_var") is False

    # Left must be boolean
    with pytest.raises(EvalError):
        evaluate("1 and true")

    # Right must be boolean when evaluated
    with pytest.raises(EvalError):
        evaluate("true and 1")


def test_short_circuit_or():
    # Left is true, right is not evaluated
    assert evaluate("true or (1 / 0)") is True
    assert evaluate("true or undefined_var") is True

    # Left must be boolean
    with pytest.raises(EvalError):
        evaluate("1 or false")

    # Right must be boolean when evaluated
    with pytest.raises(EvalError):
        evaluate("false or 1")


def test_lazy_if():
    assert evaluate('if(1 < 2, "yes", 1 / 0)') == "yes"
    assert evaluate('if(1 > 2, 1 / 0, "no")') == "no"


def test_if_errors():
    # Condition must be boolean
    with pytest.raises(EvalError):
        evaluate("if(1, 2, 3)")

    # Arity errors
    with pytest.raises(EvalError) as exc_info:
        evaluate("if(true, 1)")
    assert "if() takes 3 argument(s), got 2" in str(exc_info.value)


def test_builtin_abs():
    assert evaluate("abs(-5.5)") == 5.5
    assert evaluate("abs(3.0)") == 3.0

    with pytest.raises(EvalError) as exc_info:
        evaluate("abs(1, 2)")
    assert "abs() takes 1 argument(s), got 2" in str(exc_info.value)

    with pytest.raises(EvalError):
        evaluate('abs("hello")')


def test_builtin_min_max():
    assert evaluate("min(5, 2, 8, 1.5)") == 1.5
    assert evaluate("max(5, 2, 8, 1.5)") == 8.0

    with pytest.raises(EvalError):
        evaluate("min()")
    with pytest.raises(EvalError):
        evaluate("max()")
    with pytest.raises(EvalError):
        evaluate('min(1, "bad")')


def test_builtin_round():
    # Banker's rounding
    assert evaluate("round(2.5)") == 2.0
    assert evaluate("round(3.5)") == 4.0
    assert evaluate("round(2.556, 2)") == 2.56
    assert evaluate("round(2.554, 2)") == 2.55

    # Non-whole number for n
    with pytest.raises(EvalError):
        evaluate("round(2.555, 1.5)")


def test_builtin_len():
    assert evaluate('len("")') == 0.0
    assert evaluate('len("abc")') == 3.0

    with pytest.raises(EvalError):
        evaluate("len(123)")
    with pytest.raises(EvalError):
        evaluate("len()")


def test_builtin_upper_lower():
    assert evaluate('upper("hello World")') == "HELLO WORLD"
    assert evaluate('lower("HELLO World")') == "hello world"

    with pytest.raises(EvalError):
        evaluate("upper(123)")
    with pytest.raises(EvalError):
        evaluate("lower(true)")


def test_builtin_str():
    assert evaluate("str(3.0)") == "3"
    assert evaluate("str(-4.0)") == "-4"
    assert evaluate("str(0.5)") == "0.5"
    assert evaluate("str(true)") == "true"
    assert evaluate("str(false)") == "false"
    assert evaluate('str("abc")') == "abc"


def test_builtin_num():
    assert evaluate('num(" 4.5 ")') == 4.5
    assert evaluate('num("1e3")') == 1000.0
    assert evaluate('num("-42")') == -42.0

    with pytest.raises(EvalError):
        evaluate('num("not_a_number")')
    with pytest.raises(EvalError):
        evaluate("num(123)")


def test_undefined_variable():
    with pytest.raises(EvalError) as exc_info:
        evaluate("x + 1", {})
    assert str(exc_info.value) == "undefined variable: x"


def test_undefined_function():
    with pytest.raises(EvalError) as exc_info:
        evaluate("unknown_fn(1)")
    assert str(exc_info.value) == "undefined function: unknown_fn"

    # Function namespace cannot fall back to variable and vice versa
    with pytest.raises(EvalError):
        evaluate("x()", {"x": 1.0})
    with pytest.raises(EvalError):
        evaluate("abs + 1")


def test_division_and_modulo_by_zero():
    with pytest.raises(EvalError) as exc_info:
        evaluate("10 / 0")
    assert str(exc_info.value) == "division by zero"

    with pytest.raises(EvalError) as exc_info:
        evaluate("10 % 0")
    assert str(exc_info.value) == "modulo by zero"


def test_env_immutability():
    env = {"a": 10.0, "b": "hello"}
    evaluate("a + 5", env)
    assert env == {"a": 10.0, "b": "hello"}


def test_env_invalid_types():
    with pytest.raises(EvalError) as exc_info:
        evaluate("x", {"x": 2})  # int is not accepted
    assert "unsupported value for x: 2" in str(exc_info.value)

    # But unread invalid values in env must not raise
    assert evaluate("y", {"x": 2, "y": 5.0}) == 5.0


def test_string_concatenation_and_operators():
    assert evaluate('"foo" + "bar"') == "foobar"
    with pytest.raises(EvalError):
        evaluate('"foo" - "bar"')
    with pytest.raises(EvalError):
        evaluate('"foo" + 1')


def test_repl_acceptance_scenario():
    input_data = 'x = 2\nx * 3\n:vars\n1/0\n"a\\nb"\n:quit\n'
    res = subprocess.run(
        [sys.executable, "-m", "minilang"],
        input=input_data,
        text=True,
        capture_output=True,
        cwd=str(REPO_ROOT),
    )
    assert res.returncode == 0
    expected = '6\nx = 2\nerror: division by zero\n"a\\nb"\n'
    assert res.stdout.replace("\r\n", "\n") == expected


def test_repl_scenario_assignment_and_variables():
    input_data = "a = 10\nb = 20.5\n  \n:vars\na + b\n:quit\n"
    res = subprocess.run(
        [sys.executable, "-m", "minilang"],
        input=input_data,
        text=True,
        capture_output=True,
        cwd=str(REPO_ROOT),
    )
    assert res.returncode == 0
    expected = "a = 10\nb = 20.5\n30.5\n"
    assert res.stdout.replace("\r\n", "\n") == expected


def test_repl_scenario_errors_and_recovery():
    input_data = "1 = 2\nfoo\n1 + 1\n:quit\n"
    res = subprocess.run(
        [sys.executable, "-m", "minilang"],
        input=input_data,
        text=True,
        capture_output=True,
        cwd=str(REPO_ROOT),
    )
    assert res.returncode == 0
    lines = [line for line in res.stdout.replace("\r\n", "\n").split("\n") if line]
    assert len(lines) == 3
    assert lines[0].startswith("error: ")
    assert lines[1] == "error: undefined variable: foo"
    assert lines[2] == "2"


def test_repl_scenario_eof():
    input_data = "1 + 2\n3 * 4\n"
    res = subprocess.run(
        [sys.executable, "-m", "minilang"],
        input=input_data,
        text=True,
        capture_output=True,
        cwd=str(REPO_ROOT),
    )
    assert res.returncode == 0
    expected = "3\n12\n"
    assert res.stdout.replace("\r\n", "\n") == expected
