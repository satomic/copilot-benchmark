"""Test suite for minilang."""

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

ROOT = Path(__file__).resolve().parent.parent


def run_repl(input_text):
    return subprocess.run(
        [sys.executable, "-m", "minilang"],
        input=input_text,
        capture_output=True,
        text=True,
        cwd=ROOT,
    )


# ---------------------------------------------------------------- lexer


def test_lex_numbers():
    tokens = tokenize("123 1.5 .5 1e3 1.2e-4 2E+8")
    assert [t.kind for t in tokens] == ["NUMBER"] * 6
    assert [t.value for t in tokens] == [123.0, 1.5, 0.5, 1000.0, 1.2e-4, 2e8]
    assert all(type(t.value) is float for t in tokens)


def test_lex_number_trailing_dot_is_error():
    with pytest.raises(LexError):
        tokenize("1.")


def test_lex_strings_and_escapes():
    tokens = tokenize(r'"a\nb\t\"q\\"')
    assert tokens[0].kind == "STRING"
    assert tokens[0].value == 'a\nb\t"q\\'


def test_lex_bad_escape():
    with pytest.raises(LexError):
        tokenize('"bad \\q escape"')


def test_lex_unterminated_string():
    with pytest.raises(LexError):
        tokenize('"unterminated')


def test_lex_newline_inside_string():
    with pytest.raises(LexError):
        tokenize('"a\nb"')


def test_lex_comments_are_ignored():
    tokens = tokenize("1 + 1 # a comment\n# whole line\n2")
    assert [t.value for t in tokens] == [1.0, "+", 1.0, 2.0]


def test_lex_single_equals_is_error():
    with pytest.raises(LexError):
        tokenize("1 = 2")


def test_lex_unexpected_character():
    with pytest.raises(LexError):
        tokenize("a @ b")


def test_lex_keywords_and_idents():
    tokens = tokenize("true false and or not foo _bar9")
    assert [t.kind for t in tokens] == ["KEYWORD"] * 5 + ["IDENT"] * 2
    assert tokens[5].value == "foo"


def test_lex_token_positions():
    tokens = tokenize("12 +  \"ab\"")
    assert [(t.kind, t.position) for t in tokens] == [
        ("NUMBER", 0),
        ("OP", 3),
        ("STRING", 6),
    ]
    # No EOF token is produced.
    assert all(t.kind != "EOF" for t in tokens)


def test_lex_error_position():
    try:
        tokenize("1 + @")
    except LexError as exc:
        assert exc.position == 4
    else:
        raise AssertionError("expected LexError")


# ---------------------------------------------------------------- parser


def test_parse_does_not_evaluate():
    parse("1 / 0")


def test_parse_trailing_input_is_error():
    with pytest.raises(ParseError):
        parse("1 2")


def test_parse_unclosed_paren_is_error():
    with pytest.raises(ParseError):
        parse("(1")


def test_parse_empty_source_is_error():
    with pytest.raises(ParseError):
        parse("")


def test_parse_comment_only_source_is_error():
    with pytest.raises(ParseError):
        parse("# only a comment")


def test_parse_comparison_is_non_associative():
    with pytest.raises(ParseError):
        parse("1 < 2 < 3")


def test_parse_error_position():
    try:
        parse("1 + )")
    except ParseError as exc:
        assert exc.position == 4
    else:
        raise AssertionError("expected ParseError")


# ---------------------------------------------------------------- evaluation: precedence


def test_additive_and_multiplicative_precedence():
    assert evaluate("1 + 2 * 3") == 7.0
    assert evaluate("(1 + 2) * 3") == 9.0


def test_left_associativity():
    assert evaluate("10 - 4 - 3") == 3.0
    assert evaluate("16 / 4 / 2") == 2.0


def test_power_is_right_associative():
    assert evaluate("2 ^ 3 ^ 2") == 512.0


def test_unary_minus_binds_looser_than_power():
    assert evaluate("-2 ^ 2") == -4.0


def test_power_negative_exponent():
    assert evaluate("2 ^ -1") == 0.5


def test_not_binds_looser_than_comparison():
    assert evaluate("not 1 == 2") is True


def test_and_binds_tighter_than_or():
    assert evaluate("true or false and false") is True
    assert evaluate("false and true or true") is True


def test_modulo_follows_python_sign_rules():
    assert evaluate("7 % 3") == 1.0
    assert evaluate("-7 % 3") == 2.0


# ---------------------------------------------------------------- evaluation: semantics


def test_string_concatenation():
    assert evaluate('"a" + "b"') == "ab"


def test_mixed_addition_is_error():
    with pytest.raises(EvalError):
        evaluate('"a" + 1')


def test_division_by_zero():
    with pytest.raises(EvalError, match="division by zero"):
        evaluate("1 / 0")


def test_modulo_by_zero():
    with pytest.raises(EvalError, match="modulo by zero"):
        evaluate("1 % 0")


def test_power_non_real_result():
    with pytest.raises(EvalError):
        evaluate("(-8) ^ 0.5")


def test_equality_across_types():
    assert evaluate("true == 1") is False
    assert evaluate('"1" == 1') is False
    assert evaluate('1 != "a"') is True
    assert evaluate("1 == 1") is True
    assert evaluate('"a" == "a"') is True


def test_string_ordering():
    assert evaluate('"abc" < "abd"') is True
    assert evaluate('"b" >= "a"') is True


def test_ordering_type_mismatch_is_error():
    with pytest.raises(EvalError):
        evaluate("1 < 'a'".replace("'", '"'))
    with pytest.raises(EvalError):
        evaluate("true < 1")


def test_short_circuit_and():
    assert evaluate("false and 1 / 0") is False


def test_short_circuit_or():
    assert evaluate("true or 1 / 0") is True


def test_and_or_require_booleans():
    with pytest.raises(EvalError):
        evaluate("1 and true")
    with pytest.raises(EvalError):
        evaluate("true and 1")
    with pytest.raises(EvalError):
        evaluate("0 or true")


def test_not_requires_boolean():
    with pytest.raises(EvalError):
        evaluate("not 1")


def test_unary_minus_requires_number():
    with pytest.raises(EvalError):
        evaluate('-"a"')


def test_undefined_variable():
    with pytest.raises(EvalError, match="undefined variable: foo"):
        evaluate("foo + 1")


def test_undefined_function():
    with pytest.raises(EvalError, match="undefined function: foo"):
        evaluate("foo(1)")


def test_call_does_not_fall_back_to_variable():
    with pytest.raises(EvalError, match="undefined function"):
        evaluate("f()", {"f": 1.0})


def test_env_variable_lookup():
    assert evaluate("x * 2", {"x": 21.0}) == 42.0


def test_env_is_not_mutated():
    env = {"x": 21.0}
    evaluate("x + 1", env)
    assert env == {"x": 21.0}


def test_env_rejects_int_values():
    with pytest.raises(EvalError, match=r"unsupported value for x: 2"):
        evaluate("x", {"x": 2})


def test_env_rejects_other_types():
    with pytest.raises(EvalError, match="unsupported value for x"):
        evaluate("x", {"x": [1]})


# ---------------------------------------------------------------- built-ins


def test_builtin_abs():
    assert evaluate("abs(-3.5)") == 3.5
    assert evaluate("abs(2)") == 2.0


def test_builtin_min_max():
    assert evaluate("min(3, 1, 2)") == 1.0
    assert evaluate("max(3, 1, 2)") == 3.0
    assert evaluate("min(5)") == 5.0


def test_builtin_min_max_require_numbers():
    with pytest.raises(EvalError):
        evaluate('min(1, "a")')
    with pytest.raises(EvalError):
        evaluate("max()")


def test_builtin_round():
    assert evaluate("round(2.5)") == 2.0  # banker's rounding
    assert evaluate("round(3.5)") == 4.0
    assert evaluate("round(2.675, 2)") == round(2.675, 2)  # matches Python
    assert evaluate("round(1.2345, 2)") == 1.23
    with pytest.raises(EvalError):
        evaluate("round(1.5, 0.5)")


def test_builtin_len():
    assert evaluate('len("hello")') == 5.0
    assert type(evaluate('len("hi")')) is float


def test_builtin_upper_lower():
    assert evaluate('upper("aBc")') == "ABC"
    assert evaluate('lower("aBc")') == "abc"


def test_builtin_str():
    assert evaluate("str(3.0)") == "3"
    assert evaluate("str(0.5)") == "0.5"
    assert evaluate("str(true)") == "true"
    assert evaluate("str(false)") == "false"
    assert evaluate('str("x")') == "x"


def test_builtin_num():
    assert evaluate('num(" 4.5 ")') == 4.5
    with pytest.raises(EvalError):
        evaluate('num("abc")')


def test_builtin_arity_message():
    with pytest.raises(EvalError, match=r"abs\(\) takes 1 argument\(s\), got 2"):
        evaluate("abs(1, 2)")


def test_if_is_lazy():
    assert evaluate('if(1 < 2, "yes", 1 / 0)') == "yes"
    assert evaluate("if(false, 1 / 0, 42)") == 42.0


def test_if_requires_boolean_condition():
    with pytest.raises(EvalError):
        evaluate("if(1, 2, 3)")


def test_if_arity():
    with pytest.raises(EvalError, match=r"if\(\) takes 3 argument\(s\), got 2"):
        evaluate("if(true, 1)")


# ---------------------------------------------------------------- errors


def test_error_str_is_plain_message():
    err = LexError("bad char", 3)
    assert str(err) == "bad char"
    assert err.position == 3


def test_errors_share_base_class():
    for exc in (LexError("x", 0), ParseError("x", 0), EvalError("x")):
        assert isinstance(exc, MiniLangError)


# ---------------------------------------------------------------- REPL


def test_repl_acceptance_scenario():
    result = run_repl('x = 2\nx * 3\n:vars\n1/0\n"a\\nb"\n:quit\n')
    assert result.returncode == 0
    assert result.stdout == '6\nx = 2\nerror: division by zero\n"a\\nb"\n'
    assert result.stderr == ""


def test_repl_assignment_prints_nothing_and_blank_lines_ignored():
    result = run_repl("\n   \ny = 1 + 1\ny\n")
    assert result.returncode == 0
    assert result.stdout == "2\n"


def test_repl_vars_sorted_and_quit():
    result = run_repl("b = 1\na = true\n:vars\n:quit\nthis never runs\n")
    assert result.returncode == 0
    assert result.stdout == "a = true\nb = 1\n"


def test_repl_error_does_not_change_env():
    result = run_repl("x = 5\nx = 1 / 0\nx\n")
    assert result.returncode == 0
    assert result.stdout == "error: division by zero\n5\n"


def test_repl_boolean_and_string_formatting():
    result = run_repl('1 < 2\n"hi" + "!"\n0.5\n')
    assert result.returncode == 0
    assert result.stdout == 'true\n"hi!"\n0.5\n'
