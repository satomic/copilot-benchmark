import os
from pathlib import Path
import subprocess
import sys

import pytest

import minilang
from minilang import EvalError, LexError, MiniLangError, ParseError, evaluate, parse, tokenize


def run_repl(source):
    result = subprocess.run(
        [sys.executable, "-B", "-m", "minilang"],
        input=source,
        text=True,
        capture_output=True,
        cwd=Path(__file__).resolve().parents[1],
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        timeout=10,
    )
    assert result.returncode == 0
    assert result.stderr == ""
    return result.stdout


def test_public_api():
    assert set(minilang.__all__) == {
        "tokenize", "parse", "evaluate", "MiniLangError", "LexError", "ParseError", "EvalError"
    }
    assert all(hasattr(minilang, name) for name in minilang.__all__)


def test_error_hierarchy_and_plain_message():
    for error_type in (MiniLangError, LexError, ParseError, EvalError):
        error = error_type("plain message", 4)
        assert isinstance(error, MiniLangError)
        assert error.position == 4
        assert str(error) == "plain message"
        assert error_type("message").position is None


def test_number_lexing():
    tokens = tokenize("123 1.5 .5 1e3 1.2e-4 2E+8")
    assert [t.value for t in tokens] == [123.0, 1.5, 0.5, 1000.0, 0.00012, 200000000.0]
    assert all(t.kind == "NUMBER" and type(t.value) is float for t in tokens)
    assert [t.position for t in tokens] == [0, 4, 8, 11, 15, 22]


def test_string_lexing_and_escapes():
    token, = tokenize(r'"a\n\t\r\"\\b"')
    assert (token.kind, token.value, token.position) == ("STRING", 'a\n\t\r"\\b', 0)
    assert evaluate('""') == ""


def test_comments_and_whitespace():
    tokens = tokenize(" \t# comment\n 1 + 1 # ending")
    assert [t.position for t in tokens] == [13, 15, 17]
    assert evaluate("# just a comment\n1 + 1") == 2.0
    assert evaluate('"# not a comment"') == "# not a comment"
    assert tokenize("# only") == []


def test_identifiers_and_keywords():
    tokens = tokenize("_a a2 Z true false and or not truex")
    assert [t.kind for t in tokens] == ["IDENT"] * 3 + ["KEYWORD"] * 5 + ["IDENT"]
    assert [t.value for t in tokens] == "_a a2 Z true false and or not truex".split()


def test_operator_tokens_and_no_eof():
    source = "+ - * / % ^ == != < <= > >= ( ) ,"
    tokens = tokenize(source)
    assert [t.value for t in tokens] == source.split()
    assert all(t.kind == "OP" and isinstance(t.position, int) for t in tokens)
    assert tokenize("") == []


@pytest.mark.parametrize("source,position", [
    ("1.", 1), ("1 = 2", 2), ("a @ b", 2), ('"bad \\q escape"', 5),
    ('"unterminated', 0), ('"a\nb"', 2), ('"a\rb"', 2),
    ('"abc\\', 0), ("!", 0), (".", 0), ("1e", 1), ("1e+", 1),
    ("2E-", 1), ("1.2.3", 3), ("'x'", 0), ("[1]", 0), ("é", 0),
])
def test_lex_errors_have_positions(source, position):
    with pytest.raises(LexError) as caught:
        tokenize(source)
    assert caught.value.position == position


def test_additive_and_multiplicative_precedence():
    assert evaluate("1 + 2 * 3") == 7.0
    assert evaluate("20 - 12 / 3 + 7 % 3") == 17.0
    assert evaluate("10 - 3 - 2") == 5.0
    assert evaluate("24 / 4 / 2") == 3.0
    assert evaluate("20 % 6 * 3") == 6.0


def test_parentheses():
    assert evaluate("(1 + 2) * 3") == 9.0
    assert evaluate("(((2)))") == 2.0


def test_power_is_right_associative():
    assert evaluate("2 ^ 3 ^ 2") == 512.0
    assert evaluate("(2 ^ 3) ^ 2") == 64.0
    assert evaluate("2 * 3 ^ 2") == 18.0


def test_unary_minus_and_power():
    assert evaluate("-2 ^ 2") == -4.0
    assert evaluate("(-2) ^ 2") == 4.0
    assert evaluate("2 ^ -1") == 0.5
    assert evaluate("2 ^ -2 ^ 2") == 0.0625
    assert evaluate("--2") == 2.0
    assert evaluate("3 * -2") == -6.0


def test_not_and_comparison_precedence():
    assert evaluate("not 1 == 2") is True
    assert evaluate("not not true") is True
    assert evaluate("not 1 + 2 * 3 >= 7") is False


def test_boolean_precedence_and_associativity():
    assert evaluate("true or false and false") is True
    assert evaluate("false and true or true") is True
    assert evaluate("not false and true") is True
    assert evaluate("false or false or true") is True
    assert evaluate("true and true and false") is False


@pytest.mark.parametrize("source,position", [
    ("1 < 2 < 3", 6), ("1 == 2 != 3", 7), ("1 2", 2), ("(1", 2),
    ("", 0), ("# only a comment", 16), ("1 +", 3), ("()", 1),
    ("min(1,)", 6), ("min(,1)", 4), ("min(1 2)", 6),
    ("1)", 1), ("+1", 0), ("2 ^", 3), ("(abs)(1)", 5), ("true(1)", 4),
])
def test_parse_errors_have_positions(source, position):
    with pytest.raises(ParseError) as caught:
        parse(source)
    assert caught.value.position == position


def test_comparison_can_be_explicitly_grouped():
    assert evaluate("(1 < 2) == true") is True
    assert evaluate("1 == (2 < 3)") is False
    with pytest.raises(EvalError):
        evaluate("1 < (2 < 3)")


def test_parse_does_not_evaluate():
    for source in ("1 / 0", "missing", "unknown(1)", "abs()", "true + false"):
        assert parse(source) is not None


def test_strings_are_not_syntax():
    assert evaluate('"not"') == "not"
    assert evaluate('"(" + ")"') == "()"
    with pytest.raises(ParseError):
        parse('1 "+" 2')


def test_string_concatenation():
    assert evaluate('"a" + "b"') == "ab"


@pytest.mark.parametrize("source", [
    '1 + "a"', '"a" + 1', "true + 1", "true + false",
    '"a" - "b"', '"a" * 2', "true / 2", "false % 1", "2 ^ true",
    '-"a"', "-true",
])
def test_arithmetic_requires_numbers(source):
    with pytest.raises(EvalError):
        evaluate(source)


def test_modulo_sign_rules():
    assert evaluate("7 % 3") == 1.0
    assert evaluate("-7 % 3") == 2.0
    assert evaluate("7 % -3") == -2.0
    assert evaluate("-7 % -3") == -1.0


@pytest.mark.parametrize("source,message", [
    ("1 / 0", "division by zero"), ("1 / -0", "division by zero"),
    ("1 % 0", "modulo by zero"), ("1 % -0", "modulo by zero"),
])
def test_zero_divisors(source, message):
    with pytest.raises(EvalError) as caught:
        evaluate(source)
    assert str(caught.value) == message


@pytest.mark.parametrize("source", ["(-8) ^ 0.5", "0 ^ -1", "10 ^ 10000"])
def test_invalid_power_results(source):
    with pytest.raises(EvalError):
        evaluate(source)


@pytest.mark.parametrize("source,expected", [
    ("true == 1", False), ("false == 0", False), ('1 == "1"', False),
    ("true != 1", True), ("1 == 1", True), ('"a" != "b"', True),
    ("true == true", True), ("true != false", True), ('false == "false"', False),
])
def test_type_strict_equality(source, expected):
    assert evaluate(source) is expected


@pytest.mark.parametrize("source", [
    "1 < 2", "2 <= 2", "3 > 2", "3 >= 3",
    '"a" < "b"', '"a" <= "a"', '"b" > "a"', '"b" >= "b"',
])
def test_ordering(source):
    assert evaluate(source) is True


@pytest.mark.parametrize("source", ['1 < "2"', "true < false", "false >= 0"])
def test_ordering_rejects_mixed_types_and_booleans(source):
    with pytest.raises(EvalError):
        evaluate(source)


def test_and_short_circuit():
    assert evaluate("false and 1 / 0") is False
    assert evaluate("false and missing") is False
    assert evaluate("true and false") is False
    with pytest.raises(EvalError, match="division by zero"):
        evaluate("true and 1 / 0")


def test_or_short_circuit():
    assert evaluate("true or 1 / 0") is True
    assert evaluate("true or missing") is True
    assert evaluate("false or true") is True
    with pytest.raises(EvalError, match="division by zero"):
        evaluate("false or 1 / 0")


@pytest.mark.parametrize("source", [
    "1 and true", "0 or true", '"" or false', "not 0", 'not ""',
    "true and 1", "false or 0", "1 and missing", "0 or missing",
])
def test_no_implicit_truthiness(source):
    with pytest.raises(EvalError, match="expected boolean"):
        evaluate(source)


def test_lazy_if():
    assert evaluate('if(1 < 2, "yes", 1 / 0)') == "yes"
    assert evaluate('if(false, missing(), "no")') == "no"
    assert evaluate("if(true, if(false, missing, 3), missing)") == 3.0
    with pytest.raises(EvalError, match="expected boolean"):
        evaluate("if(1, 2, 3)")
    with pytest.raises(EvalError, match="division by zero"):
        evaluate("if(false, 1, 1 / 0)")


def test_environment_values_and_immutability():
    env = {"x": 21.0, "s": "ok", "b": True, "unused": [1]}
    before = env.copy()
    assert evaluate("x * 2", env) == 42.0
    assert evaluate("s", env) == "ok"
    assert evaluate("b", env) is True
    with pytest.raises(EvalError):
        evaluate("x / 0", env)
    assert env == before


@pytest.mark.parametrize("value", [2, None, [], {}, (), complex(1, 2)])
def test_unsupported_environment_value(value):
    with pytest.raises(EvalError) as caught:
        evaluate("x", {"x": value})
    assert str(caught.value) == f"unsupported value for x: {value!r}"
    assert evaluate("false and x", {"x": value}) is False


def test_undefined_variable():
    with pytest.raises(EvalError) as caught:
        evaluate("missing")
    assert str(caught.value) == "undefined variable: missing"
    with pytest.raises(EvalError, match="undefined variable: abs"):
        evaluate("abs")


def test_undefined_function_and_separate_namespaces():
    with pytest.raises(EvalError) as caught:
        evaluate("missing()", {"missing": 2.0})
    assert str(caught.value) == "undefined function: missing"
    assert evaluate("abs(-2)", {"abs": "variable"}) == 2.0
    assert evaluate("abs", {"abs": "variable"}) == "variable"


def test_abs_builtin():
    assert evaluate("abs(-4)") == 4.0
    assert type(evaluate("abs(-4)")) is float


def test_min_and_max_builtins():
    assert evaluate("min(3, 1, 2)") == 1.0
    assert evaluate("max(3, 1, 2)") == 3.0
    assert evaluate("min(4)") == 4.0
    assert evaluate("max(-4)") == -4.0


def test_round_builtin():
    assert evaluate("round(2.5)") == 2.0
    assert evaluate("round(3.5)") == 4.0
    assert evaluate("round(-2.5)") == -2.0
    assert evaluate("round(1.25, 1)") == 1.2
    assert evaluate("round(123, -1)") == 120.0
    assert type(evaluate("round(2)")) is float


@pytest.mark.parametrize("source", ["round(1, 0.5)", "round(1, true)", 'round(1, "2")'])
def test_round_precision_validation(source):
    with pytest.raises(EvalError):
        evaluate(source)


def test_len_builtin():
    assert evaluate('len("hello")') == 5.0
    assert evaluate('len("")') == 0.0
    assert type(evaluate('len("ab")')) is float


def test_upper_and_lower_builtins():
    assert evaluate('upper("aBc")') == "ABC"
    assert evaluate('lower("aBc")') == "abc"


@pytest.mark.parametrize("source,expected", [
    ("str(3.0)", "3"), ("str(-4)", "-4"), ("str(0.5)", "0.5"),
    ("str(true)", "true"), ("str(false)", "false"), ('str("abc")', "abc"),
    (r'str("a\nb")', "a\nb"),
])
def test_str_builtin(source, expected):
    assert evaluate(source) == expected


def test_num_builtin():
    assert evaluate('num(" 4.5 ")') == 4.5
    assert evaluate('num("-1e2")') == -100.0
    assert type(evaluate('num("2")')) is float
    with pytest.raises(EvalError):
        evaluate('num("not a number")')


@pytest.mark.parametrize("source", [
    "abs(true)", 'min(1, "2")', "max(false)", 'round("1")',
    "len(2)", "upper(true)", "lower(1)", "num(2)",
])
def test_builtin_argument_types(source):
    with pytest.raises(EvalError):
        evaluate(source)


@pytest.mark.parametrize("name,expected,count", [
    ("abs", "1", 0), ("abs", "1", 2), ("min", "at least 1", 0),
    ("max", "at least 1", 0), ("round", "1 or 2", 0), ("round", "1 or 2", 3),
    ("len", "1", 0), ("upper", "1", 2), ("lower", "1", 0),
    ("str", "1", 0), ("num", "1", 2), ("if", "3", 2), ("if", "3", 4),
])
def test_builtin_arity_messages(name, expected, count):
    source = f"{name}({', '.join(['1'] * count)})"
    with pytest.raises(EvalError) as caught:
        evaluate(source)
    assert str(caught.value) == f"{name}() takes {expected} argument(s), got {count}"


def test_numeric_results_are_floats():
    for source in ("1", "-1", "1+1", "1-1", "1*1", "1/1", "1%1", "1^1",
                   "abs(1)", "min(1)", "max(1)", "round(1)", 'len("a")', 'num("1")'):
        assert type(evaluate(source)) is float


def test_repl_acceptance_scenario():
    assert run_repl('x = 2\nx * 3\n:vars\n1/0\n"a\\nb"\n:quit\n') == (
        '6\nx = 2\nerror: division by zero\n"a\\nb"\n'
    )


def test_repl_sorted_variables_and_formatting():
    assert run_repl('z = true\na = "A\\tB"\nn = -4\n:vars\n0.5\nfalse\n') == (
        'a = "A\\tB"\nn = -4\nz = true\n0.5\nfalse\n'
    )


def test_repl_failed_assignments_are_atomic():
    assert run_repl("x = 2\nx = 1/0\ny = missing\n:vars\nx == 2\nx != 2\n") == (
        "error: division by zero\nerror: undefined variable: missing\n"
        "x = 2\ntrue\nfalse\n"
    )


def test_repl_blank_lines_empty_vars_and_quit():
    assert run_repl("\n \t\n:vars\n:quit\n1/0\n") == ""
    assert run_repl("") == ""


def test_repl_lex_parse_and_eval_recovery():
    assert run_repl('1.\n(1\nunknown()\n2\n') == (
        "error: invalid number\nerror: expected ')'\nerror: undefined function: unknown\n2\n"
    )


def test_repl_escaping_and_equality_not_assignment():
    assert run_repl('s = "a\\n\\t\\r\\"\\\\b"\ns\ns == s\n') == (
        '"a\\n\\t\\r\\"\\\\b"\ntrue\n'
    )


def test_repl_reserved_words_are_not_variables():
    assert run_repl("true = 2\n:vars\ntrue\n") == "error: expected identifier\ntrue\n"
