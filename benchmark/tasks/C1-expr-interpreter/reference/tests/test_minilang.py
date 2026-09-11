"""Reference test suite for minilang (25 tests)."""
import subprocess
import sys

import pytest

from minilang import EvalError, LexError, ParseError, evaluate, parse, tokenize

BS = chr(92)


def repl(lines):
    return subprocess.run(
        [sys.executable, "-m", "minilang"],
        input="\n".join(lines) + "\n",
        capture_output=True,
        text=True,
        timeout=60,
    )


def test_number_lexing():
    assert [t.value for t in tokenize("1 1.5 .5 1e3")] == [1.0, 1.5, 0.5, 1000.0]


def test_string_lexing_with_escapes():
    (token,) = tokenize('"a' + BS + 'nb"')
    assert token.value == "a\nb"


def test_comment_is_ignored():
    assert evaluate("1 + 1 # two") == 2.0


def test_token_positions():
    assert [t.position for t in tokenize("a + b")] == [0, 2, 4]


def test_keyword_kind():
    (token,) = tokenize("true")
    assert token.kind == "KEYWORD"


def test_lex_error_unterminated_string():
    with pytest.raises(LexError):
        tokenize('"oops')


def test_lex_error_single_equals():
    with pytest.raises(LexError):
        tokenize("1 = 2")


def test_lex_error_bad_escape():
    with pytest.raises(LexError):
        tokenize('"' + BS + 'q"')


def test_lex_error_trailing_dot():
    with pytest.raises(LexError):
        tokenize("1.")


def test_multiplicative_before_additive():
    assert evaluate("1 + 2 * 3") == 7.0


def test_parentheses_override():
    assert evaluate("(1 + 2) * 3") == 9.0


def test_power_is_right_associative():
    assert evaluate("2 ^ 3 ^ 2") == 512.0


def test_unary_minus_looser_than_power():
    assert evaluate("-2 ^ 2") == -4.0


def test_negative_exponent():
    assert evaluate("2 ^ -1") == 0.5


def test_comparison_is_non_associative():
    with pytest.raises(ParseError):
        parse("1 < 2 < 3")


def test_trailing_input_is_a_parse_error():
    with pytest.raises(ParseError):
        parse("1 2")


def test_and_binds_tighter_than_or():
    assert evaluate("true or false and false") is True


def test_not_is_looser_than_comparison():
    assert evaluate("not 1 == 2") is True


def test_short_circuit_and():
    assert evaluate("false and 1 / 0") is False


def test_short_circuit_or():
    assert evaluate("true or 1 / 0") is True


def test_if_is_lazy():
    assert evaluate('if(1 < 2, "yes", 1 / 0)') == "yes"


def test_all_builtins():
    assert evaluate("abs(-2)") == 2.0
    assert evaluate("min(2, 1)") == 1.0
    assert evaluate("max(2, 1)") == 2.0
    assert evaluate("round(1.26, 1)") == 1.3
    assert evaluate('len("abc")') == 3.0
    assert evaluate('upper("a")') == "A"
    assert evaluate('lower("A")') == "a"
    assert evaluate("str(2.0)") == "2"
    assert evaluate('num("2.5")') == 2.5
    assert evaluate("if(true, 1, 2)") == 1.0


def test_undefined_variable_and_function():
    with pytest.raises(EvalError) as ei:
        evaluate("zz")
    assert str(ei.value) == "undefined variable: zz"
    with pytest.raises(EvalError) as ei:
        evaluate("zz(1)")
    assert str(ei.value) == "undefined function: zz"


def test_division_by_zero_and_env_immutability():
    with pytest.raises(EvalError) as ei:
        evaluate("1 / 0")
    assert str(ei.value) == "division by zero"
    env = {"x": 1.0}
    evaluate("x + 1", env)
    assert env == {"x": 1.0}


def test_repl_assignment_and_vars():
    p = repl(["x = 2", "x * 3", ":vars", ":quit"])
    assert p.returncode == 0
    assert p.stdout.splitlines() == ["6", "x = 2"]


def test_repl_reports_errors_and_continues():
    p = repl(["1 / 0", "1 + 1"])
    assert p.stdout.splitlines() == ["error: division by zero", "2"]


def test_repl_formats_strings_with_escapes():
    p = repl(['"a' + BS + 'nb"'])
    assert p.stdout.splitlines() == ['"a' + BS + 'nb"']
