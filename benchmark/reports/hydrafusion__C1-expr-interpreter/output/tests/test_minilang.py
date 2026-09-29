import subprocess
import sys

import pytest

from minilang import EvalError, LexError, ParseError, evaluate, parse, tokenize


def test_number_lexing():
    tokens = tokenize("123 1.5 .5 1e3 1.2e-4 2E+8")
    assert [token.value for token in tokens] == [
        123.0, 1.5, 0.5, 1000.0, 0.00012, 200000000.0
    ]
    assert all(token.kind == "NUMBER" for token in tokens)


def test_string_lexing_and_escapes():
    token = tokenize(r'"a\n\t\r\"\\b"')[0]
    assert (token.kind, token.value, token.position) == (
        "STRING", 'a\n\t\r"\\b', 0
    )


def test_comments_and_positions():
    tokens = tokenize("# first\n  2 # second")
    assert len(tokens) == 1
    assert tokens[0].position == 10


def test_invalid_lexemes():
    for source in ('"unterminated', "1.", "1 = 2", "a @ b", r'"bad \q escape"'):
        with pytest.raises(LexError) as caught:
            tokenize(source)
        assert caught.value.position is not None


def test_public_token_kinds():
    assert [token.kind for token in tokenize('1 "x" name true +')] == [
        "NUMBER", "STRING", "IDENT", "KEYWORD", "OP"
    ]


def test_multiplicative_precedence():
    assert evaluate("1 + 2 * 3") == 7.0


def test_parenthesized_precedence():
    assert evaluate("(1 + 2) * 3") == 9.0


def test_boolean_precedence():
    assert evaluate("false or true and false") is False


def test_not_binds_looser_than_comparison():
    assert evaluate("not 1 == 2") is True


def test_power_is_right_associative():
    assert evaluate("2 ^ 3 ^ 2") == 512.0


def test_unary_minus_binds_looser_than_power():
    assert evaluate("-2 ^ 2") == -4.0
    assert evaluate("2 ^ -1") == 0.5


def test_left_associative_arithmetic():
    assert evaluate("20 / 5 * 2 - 3 + 1") == 6.0


def test_non_associative_comparison():
    with pytest.raises(ParseError) as caught:
        parse("1 < 2 < 3")
    assert caught.value.position == 6


def test_parse_errors_and_parse_does_not_evaluate():
    parse("1 / 0")
    for source in ("1 2", "(1", "", "# only a comment"):
        with pytest.raises(ParseError):
            parse(source)


def test_numeric_operations_and_modulo_sign():
    assert evaluate("7 % 3") == 1.0
    assert evaluate("-7 % 3") == 2.0


def test_string_concatenation():
    assert evaluate('"a" + "b"') == "ab"
    with pytest.raises(EvalError):
        evaluate('"a" + 1')


def test_equality_is_type_sensitive():
    assert evaluate("true == 1") is False
    assert evaluate('"1" != 1') is True


def test_ordering():
    assert evaluate('"a" < "b"') is True
    assert evaluate("2 >= 2") is True
    with pytest.raises(EvalError):
        evaluate("true < false")


def test_short_circuit_and():
    assert evaluate("false and 1 / 0") is False


def test_short_circuit_or():
    assert evaluate("true or 1 / 0") is True


def test_boolean_operators_require_booleans():
    for source in ("1 and true", "false or 1", "not 1"):
        with pytest.raises(EvalError):
            evaluate(source)


def test_lazy_if():
    assert evaluate('if(1 < 2, "yes", 1 / 0)') == "yes"
    assert evaluate("if(false, missing, 3)") == 3.0


def test_abs_builtin():
    assert evaluate("abs(-2.5)") == 2.5


def test_min_and_max_builtins():
    assert evaluate("min(3, 1, 2)") == 1.0
    assert evaluate("max(3, 1, 2)") == 3.0


def test_round_builtin():
    assert evaluate("round(2.5)") == 2.0
    assert evaluate("round(1.25, 1)") == 1.2
    with pytest.raises(EvalError):
        evaluate("round(1.2, 0.5)")


def test_len_builtin():
    assert evaluate('len("hello")') == 5.0


def test_case_builtins():
    assert evaluate('upper("Ab")') == "AB"
    assert evaluate('lower("Ab")') == "ab"


def test_str_builtin():
    assert evaluate("str(3.0)") == "3"
    assert evaluate("str(true)") == "true"
    assert evaluate('str("x")') == "x"


def test_num_builtin():
    assert evaluate('num(" 4.5 ")') == 4.5
    with pytest.raises(EvalError):
        evaluate('num("no")')


def test_builtin_arity_and_types():
    with pytest.raises(EvalError, match=r"abs\(\) takes 1 argument\(s\), got 2"):
        evaluate("abs(1, 2)")
    with pytest.raises(EvalError):
        evaluate('min(1, "x")')


def test_undefined_variable():
    with pytest.raises(EvalError, match="undefined variable: missing"):
        evaluate("missing")


def test_undefined_function():
    with pytest.raises(EvalError, match="undefined function: missing"):
        evaluate("missing()")


def test_division_and_modulo_by_zero():
    with pytest.raises(EvalError, match="division by zero"):
        evaluate("1 / 0")
    with pytest.raises(EvalError, match="modulo by zero"):
        evaluate("1 % 0")


def test_non_real_power():
    with pytest.raises(EvalError):
        evaluate("(-8) ^ 0.5")


def test_environment_and_immutability():
    environment = {"x": 21.0}
    assert evaluate("x * 2", environment) == 42.0
    assert environment == {"x": 21.0}


def test_unsupported_environment_value():
    with pytest.raises(EvalError, match="unsupported value for x: 2"):
        evaluate("x", {"x": 2})


def _repl(source):
    return subprocess.run(
        [sys.executable, "-m", "minilang"],
        input=source,
        text=True,
        capture_output=True,
        check=False,
    )


def test_repl_acceptance_scenario():
    result = _repl('x = 2\nx * 3\n:vars\n1/0\n"a\\nb"\n:quit\n')
    assert result.returncode == 0
    assert result.stdout == '6\nx = 2\nerror: division by zero\n"a\\nb"\n'
    assert result.stderr == ""


def test_repl_vars_are_sorted_and_values_formatted():
    result = _repl('z = true\na = "x"\n:vars\n')
    assert result.returncode == 0
    assert result.stdout == 'a = "x"\nz = true\n'


def test_repl_error_leaves_environment_unchanged():
    result = _repl("x = 4\nx = 1 / 0\nx\n:quit\n")
    assert result.returncode == 0
    assert result.stdout == "error: division by zero\n4\n"


def test_error_string_has_no_position_prefix():
    with pytest.raises(LexError) as caught:
        tokenize("@")
    assert str(caught.value) == "unexpected character: @"
