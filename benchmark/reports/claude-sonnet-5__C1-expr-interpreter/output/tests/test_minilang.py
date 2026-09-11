"""Test suite for minilang."""

import os
import subprocess
import sys

import pytest

from minilang import EvalError, LexError, ParseError, evaluate, parse, tokenize


# ---------------------------------------------------------------------------
# Lexing
# ---------------------------------------------------------------------------

def test_lex_numbers():
    toks = tokenize("123 1.5 .5 1e3 1.2e-4 2E+8")
    values = [t.value for t in toks]
    assert values == [123.0, 1.5, 0.5, 1000.0, 1.2e-4, 2e8]
    assert all(t.kind == "NUMBER" for t in toks)


def test_lex_number_trailing_dot_error():
    with pytest.raises(LexError):
        tokenize("1.")


def test_lex_string_escapes():
    toks = tokenize(r'"a\nb\tc\r\"\\d"')
    assert toks[0].kind == "STRING"
    assert toks[0].value == "a\nb\tc\r\"\\d"


def test_lex_string_bad_escape():
    with pytest.raises(LexError):
        tokenize(r'"bad \q escape"')


def test_lex_unterminated_string():
    with pytest.raises(LexError):
        tokenize('"unterminated')


def test_lex_string_no_literal_newline():
    with pytest.raises(LexError):
        tokenize('"line1\nline2"')


def test_lex_comment():
    toks = tokenize("1 + 1 # this is a comment\n")
    assert [t.kind for t in toks] == ["NUMBER", "OP", "NUMBER"]


def test_lex_keywords_not_identifiers():
    toks = tokenize("true false and or not")
    assert [t.kind for t in toks] == ["KEYWORD"] * 5


def test_lex_identifier():
    toks = tokenize("foo_bar1")
    assert toks[0].kind == "IDENT"
    assert toks[0].value == "foo_bar1"


def test_lex_single_equals_error():
    with pytest.raises(LexError):
        tokenize("x = 1")


def test_lex_unknown_char_error():
    with pytest.raises(LexError):
        tokenize("a @ b")


def test_lex_position_tracking():
    toks = tokenize("12 + 3")
    assert toks[0].position == 0
    assert toks[1].position == 3
    assert toks[2].position == 5


def test_token_has_required_attrs():
    tok = tokenize("42")[0]
    assert hasattr(tok, "kind")
    assert hasattr(tok, "value")
    assert hasattr(tok, "position")


# ---------------------------------------------------------------------------
# Precedence / grammar
# ---------------------------------------------------------------------------

def test_precedence_add_mul():
    assert evaluate("1 + 2 * 3") == 7.0


def test_precedence_parens():
    assert evaluate("(1 + 2) * 3") == 9.0


def test_power_right_associative():
    assert evaluate("2 ^ 3 ^ 2") == 512.0


def test_unary_minus_looser_than_power():
    assert evaluate("-2 ^ 2") == -4.0


def test_power_negative_exponent():
    assert evaluate("2 ^ -1") == 0.5


def test_comparison_non_associative():
    with pytest.raises(ParseError):
        parse("1 < 2 < 3")


def test_trailing_input_error():
    with pytest.raises(ParseError):
        parse("1 2")


def test_empty_source_error():
    with pytest.raises(ParseError):
        parse("")


def test_comment_only_source_error():
    with pytest.raises(ParseError):
        parse("# only a comment")


def test_not_binds_looser_than_comparison():
    assert evaluate("not 1 == 2") is True


def test_and_or_precedence():
    # and binds tighter than or
    assert evaluate("true or false and false") is True


def test_multiplicative_left_associative():
    assert evaluate("8 / 4 / 2") == 1.0


def test_additive_left_associative():
    assert evaluate("10 - 3 - 2") == 5.0


def test_unterminated_paren_error():
    with pytest.raises(ParseError):
        parse("(1")


# ---------------------------------------------------------------------------
# Evaluation semantics
# ---------------------------------------------------------------------------

def test_string_concat():
    assert evaluate('"a" + "b"') == "ab"


def test_add_type_mismatch_error():
    with pytest.raises(EvalError):
        evaluate('"a" + 1')


def test_division_by_zero():
    with pytest.raises(EvalError):
        evaluate("1 / 0")


def test_modulo_by_zero():
    with pytest.raises(EvalError):
        evaluate("1 % 0")


def test_modulo_sign_follows_divisor():
    assert evaluate("-7 % 3") == 2.0
    assert evaluate("7 % -3") == -2.0


def test_power_complex_result_error():
    with pytest.raises(EvalError):
        evaluate("(-8) ^ 0.5")


def test_power_zero_negative_exponent_error():
    with pytest.raises(EvalError):
        evaluate("0 ^ -1")


def test_equality_across_types_is_false():
    assert evaluate("true == 1") is False


def test_equality_same_type():
    assert evaluate("1 == 1") is True
    assert evaluate('"a" == "a"') is True


def test_comparison_requires_matching_types():
    with pytest.raises(EvalError):
        evaluate('1 < "a"')


def test_string_comparison_lexicographic():
    assert evaluate('"abc" < "abd"') is True


def test_and_short_circuit():
    assert evaluate("false and 1 / 0") is False


def test_or_short_circuit():
    assert evaluate("true or 1 / 0") is True


def test_and_requires_boolean_operands():
    with pytest.raises(EvalError):
        evaluate("1 and true")


def test_not_requires_boolean():
    with pytest.raises(EvalError):
        evaluate("not 1")


def test_unary_minus_requires_number():
    with pytest.raises(EvalError):
        evaluate('-"a"')


def test_undefined_variable():
    with pytest.raises(EvalError) as exc_info:
        evaluate("x + 1")
    assert "undefined variable: x" in str(exc_info.value)


def test_undefined_function():
    with pytest.raises(EvalError) as exc_info:
        evaluate("foo(1)")
    assert "undefined function: foo" in str(exc_info.value)


def test_name_used_as_function_no_fallback_to_variable():
    with pytest.raises(EvalError):
        evaluate("x(1)", {"x": 5.0})


def test_env_immutability():
    env = {"x": 1.0}
    evaluate("x + 1", env)
    assert env == {"x": 1.0}


def test_env_unsupported_value_type():
    with pytest.raises(EvalError):
        evaluate("x", {"x": 5})  # int is not accepted


def test_lazy_if_only_evaluates_taken_branch():
    assert evaluate('if(1 < 2, "yes", 1 / 0)') == "yes"
    assert evaluate('if(1 > 2, 1 / 0, "no")') == "no"


def test_if_requires_boolean_condition():
    with pytest.raises(EvalError):
        evaluate('if(1, "a", "b")')


def test_error_str_has_no_position_prefix():
    try:
        evaluate("1 / 0")
    except EvalError as e:
        assert str(e) == "division by zero"


def test_lex_error_has_position():
    try:
        tokenize("1.")
    except LexError as e:
        assert e.position == 0


# ---------------------------------------------------------------------------
# Built-in functions
# ---------------------------------------------------------------------------

def test_builtin_abs():
    assert evaluate("abs(-5)") == 5.0
    assert evaluate("abs(5)") == 5.0


def test_builtin_min_max():
    assert evaluate("min(3, 1, 2)") == 1.0
    assert evaluate("max(3, 1, 2)") == 3.0


def test_builtin_round_one_arg():
    assert evaluate("round(2.5)") == 2.0  # banker's rounding
    assert evaluate("round(3.5)") == 4.0


def test_builtin_round_two_args():
    assert evaluate("round(3.14159, 2)") == 3.14


def test_builtin_round_non_whole_ndigits_error():
    with pytest.raises(EvalError):
        evaluate("round(3.14159, 1.5)")


def test_builtin_len():
    assert evaluate('len("hello")') == 5.0


def test_builtin_upper_lower():
    assert evaluate('upper("abc")') == "ABC"
    assert evaluate('lower("ABC")') == "abc"


def test_builtin_str():
    assert evaluate("str(3.0)") == "3"
    assert evaluate("str(0.5)") == "0.5"
    assert evaluate("str(true)") == "true"
    assert evaluate('str("x")') == "x"


def test_builtin_num():
    assert evaluate('num(" 4.5 ")') == 4.5


def test_builtin_num_invalid_error():
    with pytest.raises(EvalError):
        evaluate('num("not a number")')


def test_builtin_arity_error_message():
    try:
        evaluate("abs(1, 2)")
    except EvalError as e:
        assert str(e) == "abs() takes 1 argument(s), got 2"
    else:
        raise AssertionError("expected EvalError")


def test_builtin_type_error():
    with pytest.raises(EvalError):
        evaluate('abs("x")')


# ---------------------------------------------------------------------------
# REPL (subprocess)
# ---------------------------------------------------------------------------

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _run_repl(stdin_text):
    result = subprocess.run(
        [sys.executable, "-m", "minilang"],
        input=stdin_text,
        capture_output=True,
        text=True,
        cwd=_PROJECT_ROOT,
    )
    return result


def test_repl_full_scenario():
    stdin_text = 'x = 2\nx * 3\n:vars\n1/0\n"a\\nb"\n:quit\n'
    result = _run_repl(stdin_text)
    assert result.returncode == 0
    assert result.stdout == '6\nx = 2\nerror: division by zero\n"a\\nb"\n'


def test_repl_assignment_prints_nothing():
    result = _run_repl("y = 10\n")
    assert result.returncode == 0
    assert result.stdout == ""


def test_repl_blank_lines_ignored():
    result = _run_repl("\n   \n1 + 1\n")
    assert result.returncode == 0
    assert result.stdout == "2\n"


def test_repl_vars_empty():
    result = _run_repl(":vars\n")
    assert result.returncode == 0
    assert result.stdout == ""


def test_repl_error_continues():
    result = _run_repl("1/0\n1 + 1\n")
    assert result.returncode == 0
    assert result.stdout == "error: division by zero\n2\n"


def test_repl_quit_exit_code():
    result = _run_repl(":quit\n1 + 1\n")
    assert result.returncode == 0
    assert result.stdout == ""


def test_repl_eof_exit_code():
    result = _run_repl("1 + 1\n")
    assert result.returncode == 0
    assert result.stdout == "2\n"
