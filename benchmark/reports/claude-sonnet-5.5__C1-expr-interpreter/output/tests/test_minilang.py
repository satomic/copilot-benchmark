import subprocess
import sys
from pathlib import Path

import pytest

from minilang import EvalError, LexError, MiniLangError, ParseError, evaluate, parse, tokenize

ROOT = Path(__file__).resolve().parent.parent


def repl(text):
    p = subprocess.run(
        [sys.executable, "-m", "minilang"], input=text, capture_output=True,
        text=True, cwd=ROOT, encoding="utf-8",
    )
    return p.returncode, p.stdout.splitlines()


def err(src, env=None):
    with pytest.raises(EvalError) as e:
        evaluate(src, env)
    return str(e.value)


def test_number_lexing():
    vals = [t.value for t in tokenize("123 1.5 .5 1e3 1.2e-4 2E+8")]
    assert vals == [123.0, 1.5, 0.5, 1000.0, 1.2e-4, 2e8]
    assert all(t.kind == "NUMBER" for t in tokenize("1 2"))


def test_number_trailing_dot_is_lex_error():
    with pytest.raises(LexError) as e:
        tokenize("1.")
    assert e.value.position == 0


def test_string_escapes():
    toks = tokenize(r'"a\nb\t\r\"\\"')
    assert toks[0].kind == "STRING" and toks[0].value == 'a\nb\t\r"\\'


def test_bad_strings():
    for src in ('"abc', '"bad \\q"', '"a\nb"'):
        with pytest.raises(LexError):
            tokenize(src)


def test_lex_errors_and_positions():
    with pytest.raises(LexError) as e:
        tokenize("a @ b")
    assert e.value.position == 2 and str(e.value) == e.value.message
    with pytest.raises(LexError):
        tokenize("1 = 2")


def test_token_kinds():
    toks = tokenize("x and true + 1 <= y")
    assert [t.kind for t in toks] == ["IDENT", "KEYWORD", "KEYWORD", "OP", "NUMBER", "OP", "IDENT"]
    assert [t.position for t in toks][:3] == [0, 2, 6]


def test_comments():
    assert evaluate("# c\n1 + 1 # trailing") == 2.0
    with pytest.raises(ParseError):
        parse("# only")


def test_precedence_arith():
    assert evaluate("1 + 2 * 3") == 7.0
    assert evaluate("(1 + 2) * 3") == 9.0
    assert evaluate("10 - 4 - 3") == 3.0
    assert evaluate("100 / 10 / 5") == 2.0
    assert evaluate("7 % 3 * 2") == 2.0


def test_power():
    assert evaluate("2 ^ 3 ^ 2") == 512.0
    assert evaluate("-2 ^ 2") == -4.0
    assert evaluate("2 ^ -1") == 0.5
    assert evaluate("2 * 3 ^ 2") == 18.0


def test_modulo_signs():
    assert evaluate("7 % 3") == 1.0
    assert evaluate("-7 % 3") == 2.0
    assert evaluate("7 % -3") == -2.0


def test_precedence_logic():
    assert evaluate("true or false and false") is True
    assert evaluate("not 1 == 2") is True
    assert evaluate("not true and false") is False
    assert evaluate("1 + 1 == 2 and 2 * 2 == 4") is True


def test_comparison_non_associative():
    with pytest.raises(ParseError) as e:
        parse("1 < 2 < 3")
    assert e.value.position == 6


def test_parse_errors():
    for src in ("1 2", "(1", "", "1 +", ")", "f(1,)"):
        with pytest.raises(ParseError):
            parse(src)
    with pytest.raises(ParseError) as e:
        parse("1 2")
    assert e.value.position == 2


def test_parse_does_not_evaluate():
    parse("1 / 0")
    parse("undefined_fn(x)")


def test_strings_ops():
    assert evaluate('"a" + "b"') == "ab"
    assert evaluate('"a" < "b"') is True
    err('"a" + 1')
    err('1 < "a"')
    err("true < false")


def test_equality():
    assert evaluate("true == 1") is False
    assert evaluate('"1" == 1') is False
    assert evaluate('"a" != "b"') is True
    assert evaluate("1 == 1.0") is True
    assert evaluate("true == true") is True


def test_short_circuit():
    assert evaluate("false and 1 / 0") is False
    assert evaluate("true or 1 / 0") is True
    err("true and 1")
    err("1 and true")
    err("false or 1")
    assert err("true and 1 / 0") == "division by zero"


def test_not_and_unary_type_errors():
    err("not 1")
    err('-"a"')
    assert evaluate("--3") == 3.0


def test_lazy_if():
    assert evaluate('if(1 < 2, "yes", 1 / 0)') == "yes"
    assert evaluate("if(false, 1 / 0, 2)") == 2.0
    err("if(1, 2, 3)")
    assert err("if(true, 1)") == "if() takes 3 argument(s), got 2"


def test_zero_errors():
    assert err("1 / 0") == "division by zero"
    assert err("1 % 0") == "modulo by zero"


def test_power_errors():
    err("(-8) ^ 0.5")
    err("0 ^ -1")
    err("10 ^ 1000")


def test_undefined_names():
    assert err("y") == "undefined variable: y"
    assert err("foo(1)") == "undefined function: foo"
    assert err("abs") == "undefined variable: abs"
    assert err("x(1)", {"x": 1.0}) == "undefined function: x"


def test_env_values():
    assert evaluate("x * 2", {"x": 21.0}) == 42.0
    assert err("x", {"x": 2}) == "unsupported value for x: 2"
    assert err("x", {"x": None}) == "unsupported value for x: None"
    assert evaluate("1", {"x": 2}) == 1.0


def test_env_not_mutated():
    env = {"x": 1.0}
    evaluate("x + 1", env)
    assert env == {"x": 1.0}


def test_builtin_numeric():
    assert evaluate("abs(-3)") == 3.0
    assert evaluate("min(3, 1, 2)") == 1.0
    assert evaluate("max(3, 1, 2)") == 3.0
    assert evaluate("max(4)") == 4.0
    assert evaluate("round(2.5)") == 2.0
    assert evaluate("round(3.5)") == 4.0
    assert evaluate("round(1.2345, 2)") == 1.23
    err("round(1.5, 0.5)")
    err("min()")
    err('max(1, "a")')


def test_builtin_strings():
    assert evaluate('len("hello")') == 5.0
    assert evaluate('upper("aB")') == "AB"
    assert evaluate('lower("aB")') == "ab"
    assert evaluate("str(3.0)") == "3"
    assert evaluate("str(0.5)") == "0.5"
    assert evaluate("str(true)") == "true"
    assert evaluate('str("x")') == "x"
    assert evaluate('num(" 4.5 ")') == 4.5
    err('num("abc")')
    err('num("nan")')
    err("len(1)")


def test_arity_message():
    assert err("abs(1, 2)") == "abs() takes 1 argument(s), got 2"
    assert err("len()") == "len() takes 1 argument(s), got 0"


def test_error_hierarchy():
    assert issubclass(LexError, MiniLangError)
    assert issubclass(ParseError, MiniLangError)
    assert issubclass(EvalError, MiniLangError)
    assert EvalError("m").position is None


def test_repl_spec_example():
    code, out = repl('x = 2\nx * 3\n:vars\n1/0\n"a\\nb"\n:quit\n')
    assert code == 0
    assert out == ["6", "x = 2", "error: division by zero", '"a\\nb"']


def test_repl_eof_blank_and_formatting():
    code, out = repl("\n   \n1.25\n-4\n2 ^ 3 ^ 2\ntrue\n0.5\n")
    assert code == 0
    assert out == ["1.25", "-4", "512", "true", "0.5"]


def test_repl_errors_keep_env():
    src = 'a = 1\na = 1 / 0\nb = "s"\n:vars\nq\n1 = 2\na == 1\n:vars\n'
    code, out = repl(src)
    assert code == 0
    assert out == [
        "error: division by zero",
        'a = 1', 'b = "s"',
        "error: undefined variable: q",
        "error: unexpected '=' (did you mean '=='?)",
        "true",
        'a = 1', 'b = "s"',
    ]


def test_repl_vars_empty_and_sorted():
    assert repl(":vars\n") == (0, [])
    _, out = repl("b = true\na = 2\n:vars\n")
    assert out == ["a = 2", "b = true"]
