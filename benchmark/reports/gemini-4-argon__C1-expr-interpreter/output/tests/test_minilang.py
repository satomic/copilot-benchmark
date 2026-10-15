import subprocess
import sys
import pytest

import minilang
from minilang import (
    EvalError,
    LexError,
    MiniLangError,
    ParseError,
    evaluate,
    parse,
    tokenize,
)


def run_repl(input_text: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "minilang"],
        input=input_text,
        text=True,
        capture_output=True,
        check=False,
    )


def test_public_api_surface():
    expected = {
        "tokenize",
        "parse",
        "evaluate",
        "MiniLangError",
        "LexError",
        "ParseError",
        "EvalError",
    }
    assert set(minilang.__all__) == expected
    for name in expected:
        assert hasattr(minilang, name)


def test_error_hierarchy_and_str():
    assert issubclass(LexError, MiniLangError)
    assert issubclass(ParseError, MiniLangError)
    assert issubclass(EvalError, MiniLangError)

    err = LexError("unexpected character", 5)
    assert err.position == 5
    assert str(err) == "unexpected character"

    eval_err = EvalError("division by zero")
    assert eval_err.position is None or isinstance(eval_err.position, int)
    assert str(eval_err) == "division by zero"


def test_lexer_numbers():
    src = "123 1.5 .5 1e3 1.2e-4 2E+8"
    tokens = tokenize(src)
    assert [t.kind for t in tokens] == ["NUMBER"] * 6
    assert [t.value for t in tokens] == [123.0, 1.5, 0.5, 1000.0, 1.2e-4, 2e8]
    assert [t.position for t in tokens] == [0, 4, 8, 11, 15, 22]


def test_lexer_number_errors():
    for bad in ("1.", "1. + 2", ".", "1e", "1e+", "1e-", "1.2.3"):
        with pytest.raises(LexError) as exc_info:
            tokenize(bad)
        assert isinstance(exc_info.value.position, int)


def test_lexer_strings_and_escapes():
    src = r'"hello" "a\nb\tc\r\"\\"'
    tokens = tokenize(src)
    assert len(tokens) == 2
    assert tokens[0].kind == "STRING"
    assert tokens[0].value == "hello"
    assert tokens[0].position == 0
    assert tokens[1].kind == "STRING"
    assert tokens[1].value == 'a\nb\tc\r"\\'
    assert tokens[1].position == 8


def test_lexer_string_errors():
    for bad in ('"unterminated', '"bad \\q escape"', '"line\nbreak"', '"trailing\\'):
        with pytest.raises(LexError) as exc_info:
            tokenize(bad)
        assert isinstance(exc_info.value.position, int)


def test_lexer_identifiers_keywords_and_operators():
    src = "true false and or not foo_1 _bar + - * / % ^ == != < <= > >= ( ) ,"
    tokens = tokenize(src)
    kinds = [t.kind for t in tokens]
    values = [t.value for t in tokens]
    assert kinds[:5] == ["KEYWORD"] * 5
    assert values[:5] == ["true", "false", "and", "or", "not"]
    assert kinds[5:7] == ["IDENT", "IDENT"]
    assert values[5:7] == ["foo_1", "_bar"]
    assert kinds[7:] == ["OP"] * 15
    assert values[7:] == [
        "+", "-", "*", "/", "%", "^", "==", "!=", "<", "<=", ">", ">=", "(", ")", ","
    ]


def test_lexer_comments_and_whitespace():
    src = "# leading comment\n  10 + 20 # inline comment\n# trailing"
    tokens = tokenize(src)
    assert [(t.kind, t.value) for t in tokens] == [
        ("NUMBER", 10.0),
        ("OP", "+"),
        ("NUMBER", 20.0),
    ]
    assert evaluate("# just a comment\n1 + 1") == 2.0


def test_lexer_invalid_characters():
    for src in ("1 = 2", "a @ b", "a ! b", "$x"):
        with pytest.raises(LexError) as exc_info:
            tokenize(src)
        assert isinstance(exc_info.value.position, int)


def test_precedence_arithmetic_and_parentheses():
    assert evaluate("1 + 2 * 3") == 7.0
    assert evaluate("(1 + 2) * 3") == 9.0
    assert evaluate("10 - 3 - 2") == 5.0
    assert evaluate("20 / 5 / 2") == 2.0
    assert evaluate("2 + 3 * 4 ^ 2") == 50.0


def test_power_associativity_and_unary_minus():
    assert evaluate("2 ^ 3 ^ 2") == 512.0
    assert evaluate("-2 ^ 2") == -4.0
    assert evaluate("(-2) ^ 2") == 4.0
    assert evaluate("2 ^ -1") == 0.5
    assert evaluate("--5") == 5.0
    assert evaluate("-2 ^ -2") == -0.25


def test_modulo_and_division():
    assert evaluate("7 % 3") == 1.0
    assert evaluate("-7 % 3") == 2.0
    assert evaluate("7 % -3") == -2.0
    assert evaluate("7 / 2") == 3.5


def test_division_and_modulo_by_zero():
    with pytest.raises(EvalError) as exc_info:
        evaluate("1 / 0")
    assert str(exc_info.value) == "division by zero"

    with pytest.raises(EvalError) as exc_info:
        evaluate("1 % 0")
    assert str(exc_info.value) == "modulo by zero"


def test_invalid_exponentiation():
    with pytest.raises(EvalError):
        evaluate("(-8) ^ 0.5")
    with pytest.raises(EvalError):
        evaluate("0 ^ -1")


def test_string_concatenation_and_type_errors():
    assert evaluate('"a" + "b"') == "ab"
    for bad in ('"a" + 1', '1 + "b"', '"a" - "b"', '"a" * 2', '-"a"'):
        with pytest.raises(EvalError):
            evaluate(bad)


def test_equality_and_ordering_comparisons():
    assert evaluate("1 == 1") is True
    assert evaluate("1 != 2") is True
    assert evaluate("true == 1") is False
    assert evaluate("false == 0") is False
    assert evaluate('1 == "1"') is False
    assert evaluate('1 != "1"') is True
    assert evaluate("1 < 2") is True
    assert evaluate("2 <= 2") is True
    assert evaluate("3 > 2") is True
    assert evaluate("3 >= 3") is True
    assert evaluate('"abc" < "abd"') is True
    assert evaluate('"b" > "a"') is True

    for bad in ("1 < true", '"a" < 1', "true < false", "true >= true"):
        with pytest.raises(EvalError):
            evaluate(bad)


def test_non_associative_comparison_and_parse_errors():
    for src in (
        "1 < 2 < 3",
        "1 == 1 == true",
        "1 2",
        "(1",
        "1 +",
        "",
        "   ",
        "# only a comment",
        "abs(1,)",
    ):
        with pytest.raises(ParseError) as exc_info:
            parse(src)
        assert isinstance(exc_info.value.position, int)


def test_parse_does_not_evaluate():
    ast = parse("1 / 0")
    assert ast is not None
    ast2 = parse("unknown_func(unknown_var)")
    assert ast2 is not None


def test_boolean_precedence_and_short_circuit():
    assert evaluate("not 1 == 2") is True
    assert evaluate("not true == false") is True
    assert evaluate("true or false and false") is True
    assert evaluate("(true or false) and false") is False
    assert evaluate("false and 1 / 0") is False
    assert evaluate("true or 1 / 0") is True
    assert evaluate("not not true") is True

    for bad in ("1 and true", "true and 1", "1 or false", "false or 1", "not 0", "not \"\""):
        with pytest.raises(EvalError):
            evaluate(bad)


def test_lazy_if_builtin():
    assert evaluate('if(1 < 2, "yes", 1 / 0)') == "yes"
    assert evaluate('if(1 > 2, 1 / 0, "no")') == "no"

    with pytest.raises(EvalError):
        evaluate("if(1, 2, 3)")

    with pytest.raises(EvalError) as exc_info:
        evaluate("if(true, 1)")
    assert str(exc_info.value) == "if() takes 3 argument(s), got 2"


def test_numeric_builtins():
    assert evaluate("abs(-5)") == 5.0
    assert evaluate("abs(3.5)") == 3.5
    assert evaluate("min(3, 1, 2)") == 1.0
    assert evaluate("min(42)") == 42.0
    assert evaluate("max(3, 1, 2)") == 3.0
    assert evaluate("max(-10, -2)") == -2.0
    assert evaluate("round(2.5)") == 2.0
    assert evaluate("round(3.5)") == 4.0
    assert evaluate("round(3.14159, 2)") == 3.14

    with pytest.raises(EvalError):
        evaluate("round(3.14, 1.5)")
    with pytest.raises(EvalError):
        evaluate("min()")
    with pytest.raises(EvalError):
        evaluate("max()")


def test_string_and_conversion_builtins():
    assert evaluate('len("hello")') == 5.0
    assert evaluate('len("")') == 0.0
    assert evaluate('upper("Hello!")') == "HELLO!"
    assert evaluate('lower("Hello!")') == "hello!"
    assert evaluate("str(3.0)") == "3"
    assert evaluate("str(3.25)") == "3.25"
    assert evaluate("str(true)") == "true"
    assert evaluate("str(false)") == "false"
    assert evaluate('str("abc")') == "abc"
    assert evaluate('num(" 4.5 ")') == 4.5
    assert evaluate('num("-1e2")') == -100.0

    for bad in ('num("abc")', 'num("")', 'num("1.")', 'num("inf")', "len(123)"):
        with pytest.raises(EvalError):
            evaluate(bad)


def test_builtin_arity_error_messages():
    with pytest.raises(EvalError) as exc_info:
        evaluate("abs(1, 2)")
    assert str(exc_info.value) == "abs() takes 1 argument(s), got 2"

    with pytest.raises(EvalError) as exc_info:
        evaluate("len()")
    assert str(exc_info.value) == "len() takes 1 argument(s), got 0"


def test_variables_and_env_immutability():
    env = {"x": 21.0, "name": "world", "flag": True}
    snapshot = dict(env)
    assert evaluate("x * 2", env) == 42.0
    assert evaluate('"hello " + name', env) == "hello world"
    assert evaluate("not flag", env) is False
    assert env == snapshot


def test_undefined_variable_and_function_errors():
    with pytest.raises(EvalError) as exc_info:
        evaluate("missing_var + 1")
    assert str(exc_info.value) == "undefined variable: missing_var"

    with pytest.raises(EvalError) as exc_info:
        evaluate("unknown_fn(1)")
    assert str(exc_info.value) == "undefined function: unknown_fn"

    # Function name used as variable does not fall back to builtin
    with pytest.raises(EvalError) as exc_info:
        evaluate("abs")
    assert str(exc_info.value) == "undefined variable: abs"

    # Variable name used as function does not fall back to variable
    with pytest.raises(EvalError) as exc_info:
        evaluate("x(1)", {"x": 10.0})
    assert str(exc_info.value) == "undefined function: x"


def test_unsupported_env_values():
    with pytest.raises(EvalError) as exc_info:
        evaluate("x + 1", {"x": 2})
    assert str(exc_info.value) == "unsupported value for x: 2"

    with pytest.raises(EvalError) as exc_info:
        evaluate("x", {"x": None})
    assert str(exc_info.value) == "unsupported value for x: None"


def test_repl_acceptance_scenario():
    stdin_data = 'x = 2\nx * 3\n:vars\n1/0\n"a\\nb"\n:quit\n100\n'
    proc = run_repl(stdin_data)
    assert proc.returncode == 0
    assert proc.stdout.splitlines() == [
        "6",
        "x = 2",
        "error: division by zero",
        '"a\\nb"',
    ]


def test_repl_vars_sorting_and_blank_lines():
    stdin_data = '\n   \nz = 1.5\na = true\nm = "hi\\tthere"\n:vars\n'
    proc = run_repl(stdin_data)
    assert proc.returncode == 0
    assert proc.stdout.splitlines() == [
        "a = true",
        'm = "hi\\tthere"',
        "z = 1.5",
    ]


def test_repl_error_recovery_and_equality():
    stdin_data = "x = 10\nx = unknown_var\nx == 10\nx == 20\n"
    proc = run_repl(stdin_data)
    assert proc.returncode == 0
    assert proc.stdout.splitlines() == [
        "error: undefined variable: unknown_var",
        "true",
        "false",
    ]
