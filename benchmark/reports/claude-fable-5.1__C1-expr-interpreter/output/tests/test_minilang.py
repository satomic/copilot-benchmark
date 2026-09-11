import os
import subprocess
import sys

import pytest

from minilang import EvalError, LexError, ParseError, evaluate, parse, tokenize

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# -- lexing ------------------------------------------------------------------

def test_tokenize_numbers():
    toks = tokenize("123 1.5 .5 1e3 1.2e-4 2E+8")
    assert [t.kind for t in toks] == ["NUMBER"] * 6
    assert [t.value for t in toks] == [123.0, 1.5, 0.5, 1000.0, 1.2e-4, 2e8]
    assert [t.position for t in toks] == [0, 4, 8, 11, 15, 22]


def test_tokenize_number_trailing_dot_is_error():
    with pytest.raises(LexError) as info:
        tokenize("1.")
    assert info.value.position == 0
    with pytest.raises(LexError):
        tokenize("1e")


def test_tokenize_strings_and_escapes():
    toks = tokenize(r'"a\nb\t\"q\"\\\r"')
    assert len(toks) == 1
    assert toks[0].kind == "STRING"
    assert toks[0].value == 'a\nb\t"q"\\\r'


def test_tokenize_string_errors():
    with pytest.raises(LexError):
        tokenize('"unterminated')
    with pytest.raises(LexError) as info:
        tokenize(r'"bad \q escape"')
    assert info.value.position == 5
    with pytest.raises(LexError):
        tokenize('"line\nbreak"')


def test_tokenize_comments_and_whitespace():
    toks = tokenize("1 # comment here\n\t+ 2 # trailing")
    assert [(t.kind, t.value) for t in toks] == [("NUMBER", 1.0), ("OP", "+"), ("NUMBER", 2.0)]


def test_tokenize_keywords_idents_and_ops():
    toks = tokenize("not foo_1 and true or false == != <= >= < > ( ) , ^ %")
    kinds = [t.kind for t in toks]
    assert kinds[:6] == ["KEYWORD", "IDENT", "KEYWORD", "KEYWORD", "KEYWORD", "KEYWORD"]
    assert all(k == "OP" for k in kinds[6:])
    assert set(kinds) <= {"NUMBER", "STRING", "IDENT", "KEYWORD", "OP"}
    assert [t.value for t in toks[6:]] ==  ["==", "!=", "<=", ">=", "<", ">", "(", ")", ",", "^", "%"]


def test_tokenize_bad_characters():
    with pytest.raises(LexError) as info:
        tokenize("1 = 2")
    assert info.value.position == 2
    with pytest.raises(LexError) as info:
        tokenize("a @ b")
    assert info.value.position == 2
    assert str(info.value) == "unexpected character '@'"


# -- parsing / precedence ------------------------------------------------------

def test_parse_does_not_evaluate():
    parse("1 / 0")
    parse("undefined_name(1)")


def test_parse_errors_with_positions():
    for src, pos in (("1 2", 2), ("(1", 2), ("", 0), ("# only a comment", 16), ("1 +", 3)):
        with pytest.raises(ParseError) as info:
            parse(src)
        assert info.value.position == pos, src


def test_non_associative_comparison():
    with pytest.raises(ParseError) as info:
        parse("1 < 2 < 3")
    assert info.value.position == 6
    with pytest.raises(ParseError):
        parse("1 == 2 != 3")
    assert evaluate("(1 < 2) == true") is True


def test_precedence_or_and():
    assert evaluate("true or false and false") is True
    assert evaluate("(true or false) and false") is False
    assert evaluate("false or true and true") is True


def test_precedence_not_vs_comparison():
    assert evaluate("not 1 == 2") is True
    assert evaluate("not not true") is True
    assert evaluate("not 1 < 2 or true") is True


def test_precedence_comparison_vs_additive():
    assert evaluate("1 + 2 == 3") is True
    assert evaluate("2 * 3 > 5") is True
    assert evaluate("10 - 4 <= 6") is True


def test_precedence_additive_vs_multiplicative():
    assert evaluate("1 + 2 * 3") == 7.0
    assert evaluate("(1 + 2) * 3") == 9.0
    assert evaluate("10 - 6 / 2") == 7.0
    assert evaluate("7 % 3 + 1") == 2.0


def test_left_associativity():
    assert evaluate("10 - 3 - 2") == 5.0
    assert evaluate("100 / 10 / 2") == 5.0
    assert evaluate("2 * 3 % 4") == 2.0


def test_power_right_associative_and_unary_minus():
    assert evaluate("2 ^ 3 ^ 2") == 512.0
    assert evaluate("-2 ^ 2") == -4.0
    assert evaluate("(-2) ^ 2") == 4.0
    assert evaluate("2 ^ -1") == 0.5
    assert evaluate("- - 3") == 3.0
    assert evaluate("2 * 3 ^ 2") == 18.0


# -- evaluation semantics --------------------------------------------------------

def test_plus_numbers_and_strings():
    assert evaluate("1.5 + 2") == 3.5
    assert evaluate('"a" + "b"') == "ab"
    with pytest.raises(EvalError):
        evaluate('"a" + 1')
    with pytest.raises(EvalError):
        evaluate("true + true")


def test_division_and_modulo():
    assert evaluate("7 % 3") == 1.0
    assert evaluate("-7 % 3") == 2.0
    assert evaluate("7 % -3") == -2.0
    assert evaluate("1 / 4") == 0.25
    with pytest.raises(EvalError) as info:
        evaluate("1 / 0")
    assert str(info.value) == "division by zero"
    with pytest.raises(EvalError) as info:
        evaluate("1 % 0")
    assert str(info.value) == "modulo by zero"


def test_power_non_real_result():
    with pytest.raises(EvalError):
        evaluate("(-8) ^ 0.5")
    with pytest.raises(EvalError):
        evaluate("0 ^ -1")
    with pytest.raises(EvalError):
        evaluate('"a" ^ 2')


def test_equality_across_types():
    assert evaluate("true == 1") is False
    assert evaluate("1 != true") is True
    assert evaluate('"1" == 1') is False
    assert evaluate('"a" == "a"') is True
    assert evaluate("1 == 1.0") is True
    assert evaluate("false != false") is False


def test_ordering_requires_matching_types():
    assert evaluate("1 < 2") is True
    assert evaluate('"apple" < "banana"') is True
    assert evaluate('"b" >= "a"') is True
    with pytest.raises(EvalError):
        evaluate('1 < "2"')
    with pytest.raises(EvalError):
        evaluate("true < false")


def test_short_circuit_and_or():
    assert evaluate("false and 1 / 0") is False
    assert evaluate("true or 1 / 0") is True
    assert evaluate("true and false") is False
    assert evaluate("false or false") is False
    with pytest.raises(EvalError):
        evaluate("1 and true")
    with pytest.raises(EvalError):
        evaluate("true and 1")
    with pytest.raises(EvalError):
        evaluate("false or 0")


def test_not_and_unary_minus_type_errors():
    with pytest.raises(EvalError):
        evaluate("not 1")
    with pytest.raises(EvalError):
        evaluate('-"a"')
    with pytest.raises(EvalError):
        evaluate("-true")


def test_undefined_variable_and_function():
    with pytest.raises(EvalError) as info:
        evaluate("x + 1")
    assert str(info.value) == "undefined variable: x"
    with pytest.raises(EvalError) as info:
        evaluate("foo(1)")
    assert str(info.value) == "undefined function: foo"
    # functions and variables live in separate namespaces
    with pytest.raises(EvalError) as info:
        evaluate("abs")
    assert str(info.value) == "undefined variable: abs"
    with pytest.raises(EvalError) as info:
        evaluate("x(1)", {"x": 1.0})
    assert str(info.value) == "undefined function: x"


def test_env_lookup_and_immutability():
    env = {"x": 21.0, "s": "hi", "flag": True}
    assert evaluate("x * 2", env) == 42.0
    assert evaluate("s + s", env) == "hihi"
    assert evaluate("flag and x > 1", env) is True
    assert env == {"x": 21.0, "s": "hi", "flag": True}


def test_env_rejects_unsupported_values():
    with pytest.raises(EvalError) as info:
        evaluate("n", {"n": 2})
    assert str(info.value) == "unsupported value for n: 2"
    with pytest.raises(EvalError):
        evaluate("n", {"n": None})
    with pytest.raises(EvalError):
        evaluate("n", {"n": [1.0]})


# -- builtins ---------------------------------------------------------------------

def test_builtin_abs_min_max():
    assert evaluate("abs(-3)") == 3.0
    assert evaluate("min(3, 1, 2)") == 1.0
    assert evaluate("max(3, 1, 2)") == 3.0
    assert evaluate("min(5)") == 5.0
    with pytest.raises(EvalError) as info:
        evaluate("abs(1, 2)")
    assert str(info.value) == "abs() takes 1 argument(s), got 2"
    with pytest.raises(EvalError):
        evaluate("min()")
    with pytest.raises(EvalError):
        evaluate('max(1, "2")')


def test_builtin_round():
    assert evaluate("round(2.5)") == 2.0
    assert evaluate("round(3.5)") == 4.0
    assert evaluate("round(2.567, 2)") == 2.57
    assert evaluate("round(1234, -2)") == 1200.0
    with pytest.raises(EvalError):
        evaluate("round(1.5, 0.5)")
    with pytest.raises(EvalError):
        evaluate('round("1")')
    with pytest.raises(EvalError):
        evaluate("round()")


def test_builtin_len_upper_lower():
    assert evaluate('len("hello")') == 5.0
    assert evaluate('len("")') == 0.0
    assert evaluate('upper("abc")') == "ABC"
    assert evaluate('lower("AbC")') == "abc"
    with pytest.raises(EvalError):
        evaluate("len(1)")
    with pytest.raises(EvalError):
        evaluate('upper("a", "b")')


def test_builtin_str():
    assert evaluate("str(3.0)") == "3"
    assert evaluate("str(-4)") == "-4"
    assert evaluate("str(0.5)") == "0.5"
    assert evaluate("str(true)") == "true"
    assert evaluate("str(false)") == "false"
    assert evaluate('str("a\\nb")') == "a\nb"
    assert evaluate('str(2 ^ 3 ^ 2)') == "512"


def test_builtin_num():
    assert evaluate('num(" 4.5 ")') == 4.5
    assert evaluate('num("1e3")') == 1000.0
    assert evaluate('num("-2")') == -2.0
    with pytest.raises(EvalError):
        evaluate('num("abc")')
    with pytest.raises(EvalError):
        evaluate('num("")')
    with pytest.raises(EvalError):
        evaluate("num(1)")


def test_builtin_if_is_lazy():
    assert evaluate('if(1 < 2, "yes", 1 / 0)') == "yes"
    assert evaluate('if(false, 1 / 0, "no")') == "no"
    assert evaluate("if(true, 1, 2)") == 1.0
    with pytest.raises(EvalError):
        evaluate("if(1, 2, 3)")
    with pytest.raises(EvalError) as info:
        evaluate("if(true, 1)")
    assert str(info.value) == "if() takes 3 argument(s), got 2"


def test_comment_only_and_leading_comment():
    assert evaluate("# just a comment\n1 + 1") == 2.0
    with pytest.raises(ParseError):
        parse("# only a comment")


def test_error_str_has_no_position_prefix():
    with pytest.raises(LexError) as info:
        tokenize("1 = 2")
    assert str(info.value) == "unexpected '=' (did you mean '==')?"
    assert isinstance(info.value.position, int)
    with pytest.raises(EvalError) as info:
        evaluate("1 / 0")
    assert info.value.position is None or isinstance(info.value.position, int)


# -- REPL -------------------------------------------------------------------------

def run_repl(stdin_text: str):
    proc = subprocess.run(
        [sys.executable, "-m", "minilang"],
        input=stdin_text,
        capture_output=True,
        text=True,
        cwd=PROJECT_ROOT,
    )
    return proc.returncode, proc.stdout


def test_repl_acceptance_scenario():
    code, out = run_repl('x = 2\nx * 3\n:vars\n1/0\n"a\\nb"\n:quit\n')
    assert code == 0
    assert out.splitlines() == ["6", "x = 2", "error: division by zero", '"a\\nb"']


def test_repl_formatting_and_blank_lines():
    code, out = run_repl("\n   \n0.5\n-4\n2 ^ 3 ^ 2\ntrue\n1 == 2\nstr(1.25)\n")
    assert code == 0
    assert out.splitlines() == ["0.5", "-4", "512", "true", "false", '"1.25"']


def test_repl_errors_leave_env_unchanged_and_eof_exits_zero():
    code, out = run_repl("a = 1\nb = 1 / 0\nc = 3\n1 = 2\n:vars\nq\n")
    assert code == 0
    assert out.splitlines() == [
        "error: division by zero",
        "error: unexpected '=' (did you mean '==')?",
        "a = 1",
        "c = 3",
        "error: undefined variable: q",
    ]


def test_repl_vars_empty_and_assignment_uses_env():
    code, out = run_repl(':vars\nx = 2\ny = x ^ 2\nx = x + 1\n:vars\ny == 4\n:quit\nignored\n')
    assert code == 0
    assert out.splitlines() == ["x = 3", "y = 4", "true"]
