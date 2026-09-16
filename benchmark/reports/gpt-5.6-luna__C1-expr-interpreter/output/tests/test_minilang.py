import subprocess
import sys
import pytest
from minilang import *


def test_numbers_and_strings():
    assert evaluate("1.5 + .5") == 2.0
    assert evaluate('"a\\n\\"b"') == 'a\n"b'

def test_comments():
    assert evaluate("# hi\n1 + 1") == 2.0

def test_precedence():
    assert evaluate("1 + 2 * 3") == 7.0
    assert evaluate("(1 + 2) * 3") == 9.0

def test_power():
    assert evaluate("2 ^ 3 ^ 2") == 512.0
    assert evaluate("-2 ^ 2") == -4.0
    assert evaluate("2 ^ -1") == .5

def test_comparison_and_boolean():
    assert evaluate("not 1 == 2") is True
    assert evaluate("true == 1") is False

def test_nonassociative():
    with pytest.raises(ParseError): parse("1 < 2 < 3")

def test_short_circuit():
    assert evaluate("false and 1 / 0") is False
    assert evaluate("true or 1 / 0") is True

def test_lazy_if():
    assert evaluate('if(1 < 2, "yes", 1 / 0)') == "yes"

def test_arithmetic():
    assert evaluate("7 % 3") == 1.0
    assert evaluate("-7 % 3") == 2.0
    assert evaluate('"a" + "b"') == "ab"

def test_env():
    env = {"x": 21.0}
    assert evaluate("x * 2", env) == 42.0
    assert env == {"x": 21.0}

def test_undefined_variable():
    with pytest.raises(EvalError, match="undefined variable"): evaluate("x")

def test_undefined_function():
    with pytest.raises(EvalError, match="undefined function"): evaluate("foo()")

def test_division_modulo_zero():
    with pytest.raises(EvalError, match="division by zero"): evaluate("1/0")
    with pytest.raises(EvalError, match="modulo by zero"): evaluate("1%0")

def test_abs(): assert evaluate("abs(-2)") == 2.0
def test_min_max(): assert evaluate("min(3,1,2)+max(3,1,2)") == 4.0
def test_round(): assert evaluate("round(2.5)") == 2.0 and evaluate("round(1.25, 1)") == 1.2
def test_len(): assert evaluate('len("abc")') == 3.0
def test_case(): assert evaluate('upper("ab") + lower("CD")') == "ABcd"
def test_str_num(): assert evaluate('str(3.0)') == "3" and evaluate('num(" 4.5 ")') == 4.5
def test_token_attributes():
    tokens = tokenize("true 12 x +")
    assert [t.kind for t in tokens] == ["KEYWORD", "NUMBER", "IDENT", "OP"]
    assert all(hasattr(t, a) for t in tokens for a in ("kind", "value", "position"))

def test_lex_errors():
    for src in ('"unterminated', "1.", "1 = 2", "a @ b", '"bad \\q escape"'):
        with pytest.raises(LexError): tokenize(src)

def test_parse_errors():
    for src in ("1 2", "(1", "", "# only a comment"):
        with pytest.raises(ParseError): parse(src)

def test_env_type():
    with pytest.raises(EvalError, match="unsupported value"): evaluate("x", {"x": 2})

def test_string_comparison(): assert evaluate('"a" < "b"') is True
def test_boolean_ops(): assert evaluate("true and false or true") is True
def test_builtin_arity():
    with pytest.raises(EvalError): evaluate("abs()")

def run_repl(text):
    return subprocess.run([sys.executable, "-m", "minilang"], input=text,
                          text=True, capture_output=True, check=False)

def test_repl_scenario():
    p = run_repl('x = 2\nx * 3\n:vars\n1/0\n"a\\nb"\n:quit\n')
    assert p.returncode == 0
    assert p.stdout == '6\nx = 2\nerror: division by zero\n"a\\nb"\n'

def test_repl_blank_and_eof():
    p = run_repl("\ntrue\n")
    assert p.stdout == "true\n" and p.returncode == 0

def test_repl_error_continues():
    p = run_repl("x = 1/0\n:vars\n")
    assert p.stdout == "error: division by zero\n"
