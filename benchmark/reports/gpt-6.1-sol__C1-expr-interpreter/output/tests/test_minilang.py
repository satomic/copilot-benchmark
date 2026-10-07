import math
import os
import subprocess
import sys

import pytest

import minilang
from minilang import EvalError, LexError, MiniLangError, ParseError, evaluate, parse, tokenize


def run_repl(source):
    environment = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    result = subprocess.run(
        [sys.executable, "-m", "minilang"],
        input=source,
        text=True,
        capture_output=True,
        env=environment,
        timeout=10,
    )
    assert result.returncode == 0
    assert result.stderr == ""
    return result.stdout


def test_public_api():
    assert set(minilang.__all__) == {
        "tokenize", "parse", "evaluate",
        "MiniLangError", "LexError", "ParseError", "EvalError",
    }


def test_exception_hierarchy_and_plain_messages():
    for error_type in (LexError, ParseError, EvalError):
        error = error_type("plain message", 7)
        assert isinstance(error, MiniLangError)
        assert str(error) == "plain message"
        assert error.position == 7
    assert EvalError("message").position is None


@pytest.mark.parametrize("source, expected", [
    ("123", 123.0), ("1.5", 1.5), (".5", 0.5),
    ("1e3", 1000.0), ("1.2e-4", 0.00012), ("2E+8", 200000000.0),
    ("0", 0.0), (".5e+2", 50.0),
])
def test_number_lexing(source, expected):
    token, = tokenize(source)
    assert (token.kind, token.value, token.position) == ("NUMBER", expected, 0)
    assert type(token.value) is float


def test_string_lexing_and_all_escapes():
    token, = tokenize(r'"a\nb\tc\rd\"e\\f"')
    assert token.kind == "STRING"
    assert token.value == 'a\nb\tc\rd"e\\f'
    assert token.position == 0
    assert tokenize('""')[0].value == ""


def test_comments_and_whitespace():
    tokens = tokenize(" \t# comment\r\n 1 # ignored\n + 1\n")
    assert [token.position for token in tokens] == [14, 27, 29]
    assert evaluate("# just a comment\n1 + 1") == 2.0
    assert tokenize(" # empty\n") == []
    assert evaluate('"# not a comment"') == "# not a comment"


def test_identifiers_keywords_and_positions():
    tokens = tokenize("foo _x2 true false and or not True")
    assert [token.kind for token in tokens] == [
        "IDENT", "IDENT", "KEYWORD", "KEYWORD", "KEYWORD",
        "KEYWORD", "KEYWORD", "IDENT",
    ]
    assert [token.position for token in tokens] == [0, 4, 8, 13, 19, 23, 26, 30]
    assert tokens[0].value == "foo"


def test_all_operator_tokens():
    operators = "+ - * / % ^ == != < <= > >= ( ) ,"
    tokens = tokenize(operators)
    assert [token.value for token in tokens] == operators.split()
    assert all(token.kind == "OP" for token in tokens)
    assert len(tokenize("1")) == 1


@pytest.mark.parametrize("source, position", [
    ('"unterminated', 0), ("1.", 1), ("1 = 2", 2),
    ("a @ b", 2), (r'"bad \q escape"', 5),
    ('"a\nb"', 2), ('"a\rb"', 2), (".", 0), ("1e", 2),
    ("1e+", 3), ("1e-x", 3), ("!", 0), ("&", 0),
    ("'single quotes'", 0), ("caf\u00e9", 3), ("\u0661", 0),
])
def test_lexical_errors_have_positions(source, position):
    with pytest.raises(LexError) as caught:
        tokenize(source)
    assert caught.value.position == position


def test_parse_does_not_evaluate():
    assert parse("1 / 0") is not None
    assert parse("unknown(missing)") is not None


@pytest.mark.parametrize("source, position", [
    ("1 < 2 < 3", 6), ("1 2", 2), ("(1", 2), ("", 0),
    ("# only a comment", 16), ("1 +", 3), ("()", 1),
    ("abs(1,)", 6), ("abs(,1)", 4), ("1)", 1),
    ("+1", 0), ("true()", 4), ("1(2)", 1),
    ("1 == 1 != false", 7),
])
def test_parse_errors_have_positions(source, position):
    with pytest.raises(ParseError) as caught:
        parse(source)
    assert caught.value.position == position


def test_string_operator_contents_are_not_grammar():
    assert evaluate('"not"') == "not"
    assert evaluate('"(" + ")"') == "()"
    assert evaluate('"and" == "and"') is True


def test_additive_and_multiplicative_precedence():
    assert evaluate("1 + 2 * 3") == 7.0
    assert evaluate("(1 + 2) * 3") == 9.0
    assert evaluate("10 - 3 - 2") == 5.0
    assert evaluate("20 / 2 / 5") == 2.0
    assert evaluate("20 % 6 * 3 + 1") == 7.0


def test_power_right_associativity():
    assert evaluate("2 ^ 3 ^ 2") == 512.0
    assert evaluate("(2 ^ 3) ^ 2") == 64.0
    assert evaluate("2 * 3 ^ 2") == 18.0


def test_unary_minus_and_power_precedence():
    assert evaluate("-2 ^ 2") == -4.0
    assert evaluate("(-2) ^ 2") == 4.0
    assert evaluate("2 ^ -1") == 0.5
    assert evaluate("--2") == 2.0
    assert evaluate("-2 ^ -2") == -0.25
    assert evaluate("2 ^ -2 ^ 2") == 0.0625


def test_not_and_comparison_precedence():
    assert evaluate("not 1 == 2") is True
    assert evaluate("not not true") is True
    assert evaluate("not 1 + 2 * 3 == 7") is False


def test_and_or_precedence_and_associativity():
    assert evaluate("true or false and false") is True
    assert evaluate("true and not false or false") is True
    assert evaluate("false and 1 and missing") is False
    assert evaluate("true or 1 or missing") is True


def test_parenthesized_comparisons():
    assert evaluate("(1 < 2) == true") is True
    assert evaluate("1 < 2 and 2 < 3") is True


def test_string_concatenation():
    assert evaluate('"a" + "b"') == "ab"
    assert evaluate('"" + "x"') == "x"


@pytest.mark.parametrize("source", [
    "true + false", "true + 1", '1 + "1"', '"1" - "2"',
    '"x" * 2', "true / 1", "1 % false", "true ^ 2", "-false",
])
def test_arithmetic_requires_numbers(source):
    with pytest.raises(EvalError):
        evaluate(source)


def test_modulo_sign_rules():
    assert evaluate("7 % 3") == 1.0
    assert evaluate("-7 % 3") == 2.0
    assert evaluate("7 % -3") == -2.0
    assert evaluate("-7 % -3") == -1.0


@pytest.mark.parametrize("source, message", [
    ("1 / 0", "division by zero"), ("1 / -0", "division by zero"),
    ("1 % 0", "modulo by zero"), ("1 % -0", "modulo by zero"),
])
def test_zero_divisors(source, message):
    with pytest.raises(EvalError) as caught:
        evaluate(source)
    assert str(caught.value) == message


@pytest.mark.parametrize("source", ["(-8) ^ 0.5", "0 ^ -1", "1e308 ^ 2"])
def test_invalid_exponentiation(source):
    with pytest.raises(EvalError):
        evaluate(source)


def test_equality_is_type_strict():
    assert evaluate("true == 1") is False
    assert evaluate("false == 0") is False
    assert evaluate('"1" == 1') is False
    assert evaluate("true != 1") is True
    assert evaluate("2 == 2.0") is True
    assert evaluate('"a" != "b"') is True
    assert evaluate("true == true") is True


@pytest.mark.parametrize("source, expected", [
    ("1 < 2", True), ("2 <= 2", True), ("3 > 2", True), ("2 >= 3", False),
    ('"a" < "b"', True), ('"a" <= "a"', True),
    ('"z" > "a"', True), ('"b" >= "c"', False),
])
def test_ordering(source, expected):
    assert evaluate(source) is expected


@pytest.mark.parametrize("source", ['1 < "2"', "true < false", "true >= 0"])
def test_ordering_rejects_other_types(source):
    with pytest.raises(EvalError):
        evaluate(source)


def test_short_circuit_boolean_operators():
    assert evaluate("false and 1 / 0") is False
    assert evaluate("true or 1 / 0") is True
    assert evaluate("false and missing") is False
    assert evaluate("true or unknown()") is True
    with pytest.raises(EvalError, match="division by zero"):
        evaluate("true and (1 / 0)")
    with pytest.raises(EvalError, match="division by zero"):
        evaluate("false or (1 / 0)")


@pytest.mark.parametrize("source", [
    "1 and true", "0 or true", '"" or false',
    "true and 1", "false or 1", "not 1", 'not ""',
])
def test_boolean_operators_reject_truthiness(source):
    with pytest.raises(EvalError):
        evaluate(source)


def test_left_boolean_operand_checked_first():
    with pytest.raises(EvalError, match="requires a boolean"):
        evaluate("1 and (1 / 0)")
    with pytest.raises(EvalError, match="requires a boolean"):
        evaluate("1 or missing")


def test_variable_lookup_and_types():
    assert evaluate("x * 2", {"x": 21.0}) == 42.0
    assert evaluate("s", {"s": "text"}) == "text"
    assert evaluate("b", {"b": True}) is True


def test_undefined_variable():
    with pytest.raises(EvalError) as caught:
        evaluate("missing")
    assert str(caught.value) == "undefined variable: missing"


def test_undefined_function_and_separate_namespaces():
    with pytest.raises(EvalError) as caught:
        evaluate("missing()", {"missing": 2.0})
    assert str(caught.value) == "undefined function: missing"
    with pytest.raises(EvalError, match="undefined variable: abs"):
        evaluate("abs")
    assert evaluate("abs", {"abs": "variable"}) == "variable"
    assert evaluate("abs(-2)", {"abs": "variable"}) == 2.0


@pytest.mark.parametrize("value", [2, None, [], {}, (), object()])
def test_unsupported_environment_values(value):
    with pytest.raises(EvalError) as caught:
        evaluate("x", {"x": value})
    assert str(caught.value) == f"unsupported value for x: {value!r}"
    assert evaluate("true or x", {"x": value}) is True


def test_environment_is_not_mutated():
    env = {"x": 3.0, "unused": []}
    original = env.copy()
    assert evaluate("x + 1", env) == 4.0
    assert env == original
    with pytest.raises(EvalError):
        evaluate("x / 0", env)
    assert env == original


def test_abs_min_max():
    assert evaluate("abs(-3)") == 3.0
    assert evaluate("min(3, 1, 2)") == 1.0
    assert evaluate("max(-3, 1, 2)") == 2.0
    assert evaluate("min(2)") == 2.0
    assert evaluate("max(2)") == 2.0


def test_round_bankers_rounding_and_digits():
    assert evaluate("round(2.5)") == 2.0
    assert evaluate("round(3.5)") == 4.0
    assert evaluate("round(1.234, 2)") == 1.23
    assert evaluate("round(125, -1)") == 120.0
    assert type(evaluate("round(2.5)")) is float


def test_len_upper_lower():
    assert evaluate('len("hello")') == 5.0
    assert type(evaluate('len("")')) is float
    assert evaluate('upper("aBc")') == "ABC"
    assert evaluate('lower("aBc")') == "abc"


def test_str_formatting():
    assert evaluate("str(3.0)") == "3"
    assert evaluate("str(-4)") == "-4"
    assert evaluate("str(1.25)") == "1.25"
    assert evaluate("str(true)") == "true"
    assert evaluate("str(false)") == "false"
    assert evaluate(r'str("a\nb")') == "a\nb"


def test_num_conversion():
    assert evaluate('num(" 4.5 ")') == 4.5
    assert evaluate('num("-1e3")') == -1000.0
    with pytest.raises(EvalError):
        evaluate('num("nope")')
    with pytest.raises(EvalError):
        evaluate('num("")')


def test_lazy_if_both_branches():
    assert evaluate('if(1 < 2, "yes", 1 / 0)') == "yes"
    assert evaluate('if(false, missing, "no")') == "no"
    assert evaluate("if(true, 2, unknown())") == 2.0
    assert evaluate("if(false, 1 / 0, if(true, false, missing))") is False


def test_if_requires_boolean_before_branches():
    with pytest.raises(EvalError, match="requires a boolean"):
        evaluate("if(1, 1 / 0, missing)")


@pytest.mark.parametrize("source, message", [
    ("abs()", "abs() takes 1 argument(s), got 0"),
    ("abs(1, 2)", "abs() takes 1 argument(s), got 2"),
    ("min()", "min() takes at least 1 argument(s), got 0"),
    ("max()", "max() takes at least 1 argument(s), got 0"),
    ("round()", "round() takes 1 or 2 argument(s), got 0"),
    ("round(1, 2, 3)", "round() takes 1 or 2 argument(s), got 3"),
    ("len()", "len() takes 1 argument(s), got 0"),
    ("upper()", "upper() takes 1 argument(s), got 0"),
    ("lower(1, 2)", "lower() takes 1 argument(s), got 2"),
    ("str()", "str() takes 1 argument(s), got 0"),
    ("num()", "num() takes 1 argument(s), got 0"),
    ("if(true, 1)", "if() takes 3 argument(s), got 2"),
])
def test_builtin_arity_messages(source, message):
    with pytest.raises(EvalError) as caught:
        evaluate(source)
    assert str(caught.value) == message


@pytest.mark.parametrize("source", [
    "abs(true)", 'min(1, "a")', "max(false)", 'round("1")',
    "round(1, true)", "round(1, 0.5)", "len(1)", "upper(false)",
    "lower(1)", "num(2)", "round(1, num(\"inf\"))",
    "round(num(\"inf\"))", "round(num(\"nan\"))",
])
def test_builtin_type_and_numeric_errors(source):
    with pytest.raises(EvalError):
        evaluate(source)


@pytest.mark.parametrize("source", [
    "1", "1 + 2", "-2", "2 ^ 3", "7 % 3", "abs(-1)", "min(1, 2)",
    "max(1, 2)", "round(1.5)", 'len("hi")', 'num("1")',
])
def test_all_numeric_results_are_floats(source):
    assert type(evaluate(source)) is float


def test_nonfinite_float_values():
    assert math.isinf(evaluate('num("inf")'))
    assert math.isnan(evaluate('num("nan")'))
    assert evaluate("str(x)", {"x": float("inf")}) == "inf"


def test_repl_acceptance_scenario():
    assert run_repl('x = 2\nx * 3\n:vars\n1/0\n"a\\nb"\n:quit\n') == (
        '6\nx = 2\nerror: division by zero\n"a\\nb"\n'
    )


def test_repl_sorted_vars_and_failed_assignment():
    assert run_repl(
        'z = true\na = "hi"\nn = 1.25\nz = 1/0\n:vars\nz\n'
    ) == 'error: division by zero\na = "hi"\nn = 1.25\nz = true\ntrue\n'


def test_repl_blank_lines_eof_and_quit():
    assert run_repl("\n \t\n:vars\n2 ^ 3 ^ 2\n:quit\n1/0\n") == "512\n"
    assert run_repl("") == ""
    assert run_repl(" \n-2 ^ 2\n") == "-4\n"


def test_repl_escaping_and_boolean_formatting():
    assert run_repl(r'"a\tb\rc\"d\\e"' + "\ntrue\nfalse\n0.5\n-0\n") == (
        '"a\\tb\\rc\\"d\\\\e"\ntrue\nfalse\n0.5\n0\n'
    )


def test_repl_assignment_vs_equality():
    assert run_repl("x = 2\nx == 2\nx != 2\nx = x + 1\nx\n:vars\n") == (
        "true\nfalse\n3\nx = 3\n"
    )


def test_repl_lexical_and_parse_errors_continue():
    output = run_repl("x = 3\nx = 1.\nx = (1\nx\n:vars\n")
    assert output == (
        "error: expected a digit after decimal point\n"
        "error: expected ')'\n3\nx = 3\n"
    )
