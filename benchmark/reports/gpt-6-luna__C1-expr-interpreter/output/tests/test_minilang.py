import subprocess
import sys

import pytest

from minilang import EvalError, LexError, ParseError, evaluate, parse, tokenize


def test_number_tokens_are_floats():
    assert [token.value for token in tokenize("123 1.5 .5 1e3 1.2e-4 2E+8")] == [
        123.0, 1.5, 0.5, 1000.0, 0.00012, 200000000.0
    ]


def test_token_attributes_and_kinds():
    tokens = tokenize('name "x" + true')
    assert [(token.kind, token.position) for token in tokens] == [
        ("IDENT", 0), ("STRING", 5), ("OP", 9), ("KEYWORD", 11)
    ]


def test_string_escape_lexing():
    assert tokenize(r'"a\n\t\r\"\\z"')[0].value == 'a\n\t\r"\\z'


def test_comment_and_whitespace_lexing():
    assert [token.value for token in tokenize(" 1 # ignored\n + 2 ")] == [1.0, "+" , 2.0]


def test_lexical_errors_have_positions():
    for source, position in [('1.', 1), ('=', 0), ('@', 0), ('"bad\\q"', 4), ('"open', 0)]:
        with pytest.raises(LexError) as error:
            tokenize(source)
        assert error.value.position == position


def test_additive_and_multiplicative_precedence():
    assert evaluate("1 + 2 * 3 - 4 / 2") == 5.0


def test_parentheses_override_precedence():
    assert evaluate("(1 + 2) * 3") == 9.0


def test_power_is_right_associative():
    assert evaluate("2 ^ 3 ^ 2") == 512.0


def test_unary_minus_binds_looser_than_power():
    assert evaluate("-2 ^ 2") == -4.0


def test_negative_power_exponent_is_valid():
    assert evaluate("2 ^ -1") == 0.5


def test_comparison_precedence():
    assert evaluate("1 + 2 * 3 >= 7") is True


def test_not_binds_less_tightly_than_comparison():
    assert evaluate("not 1 == 2") is True


def test_boolean_precedence_and_associativity():
    assert evaluate("true or false and false") is True
    assert evaluate("true and false and true") is False


def test_comparison_is_non_associative():
    with pytest.raises(ParseError):
        parse("1 < 2 < 3")


def test_trailing_and_empty_input_are_parse_errors():
    for source in ("1 2", "", "# comment"):
        with pytest.raises(ParseError):
            parse(source)


def test_missing_close_paren_is_parse_error():
    with pytest.raises(ParseError):
        parse("(1")


def test_parse_does_not_evaluate():
    assert parse("1 / 0") is not None


def test_addition_supports_numbers_and_strings():
    assert evaluate("1 + 2") == 3.0
    assert evaluate('"a" + "b"') == "ab"


def test_arithmetic_requires_numbers():
    with pytest.raises(EvalError):
        evaluate('"a" * 2')


def test_division_and_modulo_by_zero():
    with pytest.raises(EvalError, match="division by zero"):
        evaluate("1 / 0")
    with pytest.raises(EvalError, match="modulo by zero"):
        evaluate("1 % 0")


def test_modulo_uses_python_sign_convention():
    assert evaluate("-7 % 3") == 2.0


def test_power_rejects_non_real_results():
    with pytest.raises(EvalError):
        evaluate("(-8) ^ 0.5")


def test_equality_is_type_sensitive():
    assert evaluate("true == 1") is False
    assert evaluate('"x" != 1') is True


def test_comparisons_support_numbers_and_strings():
    assert evaluate('"a" < "b"') is True
    assert evaluate("2 >= 1") is True


def test_and_or_short_circuit():
    assert evaluate("false and (1 / 0)") is False
    assert evaluate("true or (1 / 0)") is True


def test_and_or_require_boolean_values():
    with pytest.raises(EvalError):
        evaluate("1 and true")
    with pytest.raises(EvalError):
        evaluate("true and 1")


def test_not_and_unary_minus_type_checks():
    with pytest.raises(EvalError):
        evaluate("not 1")
    with pytest.raises(EvalError):
        evaluate('-"1"')


def test_variable_lookup_and_undefined_variable():
    assert evaluate("x * 2", {"x": 21.0}) == 42.0
    with pytest.raises(EvalError, match="undefined variable: missing"):
        evaluate("missing")


def test_env_values_are_validated_only_when_read():
    with pytest.raises(EvalError, match="unsupported value for x: 2"):
        evaluate("x", {"x": 2})
    assert evaluate("true", {"x": 2}) is True


def test_evaluate_does_not_mutate_environment():
    env = {"x": 3.0}
    assert evaluate("x + 1", env) == 4.0
    assert env == {"x": 3.0}


def test_undefined_function_does_not_use_variable_value():
    with pytest.raises(EvalError, match="undefined function: mystery"):
        evaluate("mystery()", {"mystery": 1.0})


def test_abs_min_max_builtins():
    assert evaluate("abs(-3)") == 3.0
    assert evaluate("min(3, 1, 2)") == 1.0
    assert evaluate("max(3, 1, 2)") == 3.0


def test_round_builtin_and_bankers_rounding():
    assert evaluate("round(2.5)") == 2.0
    assert evaluate("round(2.345, 2)") == 2.35
    with pytest.raises(EvalError):
        evaluate("round(2, 1.5)")


def test_string_builtins():
    assert evaluate('len("hello")') == 5.0
    assert evaluate('upper("Ab")') == "AB"
    assert evaluate('lower("Ab")') == "ab"


def test_str_and_num_builtins():
    assert evaluate("str(3.0)") == "3"
    assert evaluate("str(true)") == "true"
    assert evaluate('num(" 4.5 ")') == 4.5
    with pytest.raises(EvalError):
        evaluate('num("nope")')


def test_lazy_if_builtin():
    assert evaluate('if(1 < 2, "yes", 1 / 0)') == "yes"
    assert evaluate("if(false, 1 / 0, 7)") == 7.0
    with pytest.raises(EvalError):
        evaluate("if(1, 2, 3)")


def test_builtin_arity_errors():
    with pytest.raises(EvalError, match=r"abs\(\) takes 1 argument\(s\), got 2"):
        evaluate("abs(1, 2)")
    with pytest.raises(EvalError):
        evaluate("min()")


def test_comment_in_expression():
    assert evaluate("# comment\n1 + 1") == 2.0


def test_repl_assignment_vars_and_expression():
    result = subprocess.run(
        [sys.executable, "-m", "minilang"],
        input="x = 2\nx * 3\n:vars\n:quit\n",
        text=True,
        capture_output=True,
        check=True,
    )
    assert result.stdout == "6\nx = 2\n"


def test_repl_reports_error_and_continues():
    result = subprocess.run(
        [sys.executable, "-m", "minilang"],
        input="1/0\n2+2\n",
        text=True,
        capture_output=True,
        check=True,
    )
    assert result.stdout == "error: division by zero\n4\n"


def test_repl_formats_escaped_strings():
    result = subprocess.run(
        [sys.executable, "-m", "minilang"],
        input='"a\\nb"\n:quit\n',
        text=True,
        capture_output=True,
        check=True,
    )
    assert result.stdout == '"a\\nb"\n'


def test_repl_assignment_failure_does_not_store():
    result = subprocess.run(
        [sys.executable, "-m", "minilang"],
        input="x = 1/0\n:vars\n",
        text=True,
        capture_output=True,
        check=True,
    )
    assert result.stdout == "error: division by zero\n"
