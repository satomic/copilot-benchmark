"""Tests for the minilang expression language."""

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

ROOT = Path(__file__).resolve().parents[1]


def run_repl(text: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "minilang"],
        input=text,
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=str(ROOT),
    )


def test_tokenize_numbers():
    tokens = tokenize("123 1.5 .5 1e3 1.2e-4 2E+8")
    assert [token.kind for token in tokens] == ["NUMBER"] * 6
    assert [token.value for token in tokens] == [
        123.0,
        1.5,
        0.5,
        1000.0,
        0.00012,
        200000000.0,
    ]
    assert tokens[0].position == 0
    assert all(isinstance(token.position, int) for token in tokens)


def test_tokenize_number_errors():
    assert evaluate("1.e3") == 1000.0
    for source in ("1.", "1e", "1e+", "1.e", ".", "2."):
        with pytest.raises(LexError) as caught:
            tokenize(source)
        assert isinstance(caught.value.position, int)
        assert str(caught.value) == "invalid number"


def test_tokenize_strings_and_escapes():
    tokens = tokenize(r'"hello" "a\nb" "\t" "\r" "\"" "\\" ""')
    assert [token.kind for token in tokens] == ["STRING"] * 7
    assert tokens[0].value == "hello"
    assert tokens[1].value == "a\nb"
    assert tokens[2].value == "\t"
    assert tokens[3].value == "\r"
    assert tokens[4].value == '"'
    assert tokens[5].value == "\\"
    assert tokens[6].value == ""
    assert tokens[0].position == 0


def test_tokenize_string_errors():
    with pytest.raises(LexError) as unterminated:
        tokenize('"unterminated')
    assert unterminated.value.position == 0
    with pytest.raises(LexError) as newline:
        tokenize('"line\n"')
    assert isinstance(newline.value.position, int)
    with pytest.raises(LexError) as bad:
        tokenize('"bad \\q escape"')
    assert str(bad.value) == "invalid escape"
    assert bad.value.position == 5
    for source in ('"\\a"', '"\\x41"', '"\\\'"'):
        with pytest.raises(LexError):
            tokenize(source)


def test_tokenize_comments_and_whitespace():
    tokens = tokenize("  1 + # comment\n\t2  ")
    assert [(token.kind, token.value) for token in tokens] == [
        ("NUMBER", 1.0),
        ("OP", "+"),
        ("NUMBER", 2.0),
    ]
    assert tokenize("# only\n# still") == []
    assert tokenize("1#c\n+2")[1].value == "+"


def test_tokenize_keywords_idents_and_ops():
    tokens = tokenize("true false and or not _x A1 == != <= >= < > ( ) , + -")
    kinds = [token.kind for token in tokens]
    assert kinds[:5] == ["KEYWORD"] * 5
    assert kinds[5:7] == ["IDENT", "IDENT"]
    assert all(kind == "OP" for kind in kinds[7:])
    assert [token.value for token in tokens[7:]] == [
        "==",
        "!=",
        "<=",
        ">=",
        "<",
        ">",
        "(",
        ")",
        ",",
        "+",
        "-",
    ]
    assert tokenize("trueish")[0].kind == "IDENT"


def test_tokenize_rejects_equals_and_other_characters():
    with pytest.raises(LexError) as equals:
        tokenize("1 = 2")
    assert equals.value.position == 2
    with pytest.raises(LexError) as at:
        tokenize("a @ b")
    assert at.value.position == 2
    for source in ("1 & 2", "1 | 2", "f[0]", "1;", "'hi'"):
        with pytest.raises(LexError):
            tokenize(source)
    assert not any(token.kind == "EOF" for token in tokenize("1 + 2"))


def test_token_attributes_and_public_surface():
    import minilang

    assert set(minilang.__all__) == {
        "tokenize",
        "parse",
        "evaluate",
        "MiniLangError",
        "LexError",
        "ParseError",
        "EvalError",
    }
    token = tokenize("x")[0]
    assert token.kind == "IDENT"
    assert token.value == "x"
    assert token.position == 0
    assert issubclass(LexError, MiniLangError)
    assert issubclass(ParseError, MiniLangError)
    assert issubclass(EvalError, MiniLangError)


def test_arithmetic_precedence_and_associativity():
    assert evaluate("1 + 2 * 3") == 7.0
    assert evaluate("1 * 2 + 3") == 5.0
    assert evaluate("(1 + 2) * 3") == 9.0
    assert evaluate("10 - 3 - 2") == 5.0
    assert evaluate("2 * 3 * 4") == 24.0
    assert evaluate("10 / 2 / 2") == 2.5
    assert evaluate("20 % 6 % 4") == 2.0
    assert evaluate("2 ^ 2 * 3") == 12.0
    assert evaluate("2 * 3 ^ 2") == 18.0
    assert evaluate("1 + -2") == -1.0
    assert evaluate("1 - -2") == 3.0
    assert evaluate("--5") == 5.0
    assert evaluate("---5") == -5.0
    assert type(evaluate("1 + 2")) is float


def test_power_right_associative_and_unary_minus():
    assert evaluate("2 ^ 3 ^ 2") == 512.0
    assert evaluate("2 ^ 2 ^ 2 ^ 2") == 65536.0
    assert evaluate("-2 ^ 2") == -4.0
    assert evaluate("(-2) ^ 2") == 4.0
    assert evaluate("2 ^ -1") == 0.5
    assert evaluate("4 ^ 0.5") == 2.0
    assert evaluate("-2 ^ 3") == -8.0
    assert evaluate("(-2) ^ 3") == -8.0
    assert evaluate("2^-1") == 0.5


def test_logical_precedence():
    assert evaluate("true or false and false") is True
    assert evaluate("false and false or true") is True
    assert evaluate("not false and false") is False
    assert evaluate("not true or true") is True
    assert evaluate("not 1 == 2") is True
    assert evaluate("not 1 < 2") is False
    assert evaluate("not not true") is True
    assert evaluate("not not not false") is True
    assert evaluate("true and true") is True
    assert evaluate("false or false") is False


def test_comparisons_and_equality():
    assert evaluate("1 < 2") is True
    assert evaluate("2 <= 2") is True
    assert evaluate("2 > 1") is True
    assert evaluate("1 >= 2") is False
    assert evaluate("1 == 1") is True
    assert evaluate("1 != 2") is True
    assert evaluate('"abc" < "abd"') is True
    assert evaluate('"b" > "a"') is True
    assert evaluate('"a" <= "a"') is True
    assert evaluate('"a" >= "b"') is False
    assert evaluate("true == 1") is False
    assert evaluate("true == true") is True
    assert evaluate("true != false") is True
    assert evaluate('"a" == 1') is False
    assert evaluate('1 != "1"') is True
    assert evaluate("true != 1") is True
    with pytest.raises(EvalError):
        evaluate('1 < "a"')
    with pytest.raises(EvalError):
        evaluate("true < false")
    with pytest.raises(EvalError):
        evaluate('1 <= "2"')


def test_comparison_is_non_associative():
    for source in ("1 < 2 < 3", "1 < 2 == 3", "1 <= 2 <= 3", "1 > 2 != 3"):
        with pytest.raises(ParseError) as caught:
            parse(source)
        assert isinstance(caught.value.position, int)
    with pytest.raises(ParseError) as chained:
        parse("1 < 2 < 3")
    assert chained.value.position == 6
    assert evaluate("1 < 2 + 3") is True
    assert evaluate("1 + 2 < 3 + 4") is True


def test_parse_errors_and_positions():
    for source in ("1 < 2 < 3", "1 2", "(1", "", "# only a comment", "   ", "#\n#"):
        with pytest.raises(ParseError) as caught:
            parse(source)
        assert isinstance(caught.value.position, int)
        assert "position" not in str(caught.value)
    with pytest.raises(ParseError) as empty:
        parse("")
    assert empty.value.position == 0
    with pytest.raises(ParseError) as trailing:
        parse("1 2")
    assert trailing.value.position == 2
    for source in ("()", "1 +", "f(1,)", "f(,1)", "+1", "and true"):
        with pytest.raises(ParseError):
            parse(source)


def test_parse_does_not_evaluate():
    tree = parse("1 / 0")
    assert tree is not None
    parse("undefined_name + missing()")
    parse('if(true, 1 / 0, 2)')


def test_strings_concatenation_and_comments():
    assert evaluate('"a" + "b"') == "ab"
    assert evaluate(r'"a\nb"') == "a\nb"
    assert evaluate(r'"\""') == '"'
    assert evaluate(r'"\\"') == "\\"
    assert evaluate("# just a comment\n1 + 1") == 2.0
    assert evaluate("1 + # c\n 2") == 3.0
    assert evaluate("1#c\n+2") == 3.0
    with pytest.raises(EvalError):
        evaluate('"a" + 1')
    with pytest.raises(EvalError):
        evaluate('1 + "a"')


def test_modulo_sign_and_division():
    assert evaluate("7 % 3") == 1.0
    assert evaluate("-7 % 3") == 2.0
    assert evaluate("7 % -3") == -2.0
    assert evaluate("5.5 % 2") == 1.5
    assert evaluate("8 / 2") == 4.0
    assert evaluate("-7 / 2") == -3.5
    with pytest.raises(EvalError) as div:
        evaluate("1 / 0")
    assert str(div.value) == "division by zero"
    with pytest.raises(EvalError) as mod:
        evaluate("1 % 0")
    assert str(mod.value) == "modulo by zero"
    with pytest.raises(EvalError) as nested:
        evaluate("1 / (2 - 2)")
    assert str(nested.value) == "division by zero"


def test_short_circuit_and_or():
    assert evaluate("false and 1 / 0") is False
    assert evaluate("true or 1 / 0") is True
    assert evaluate("false and undefined_name") is False
    assert evaluate("true or undefined_name") is True
    assert evaluate("false and abs()") is False
    assert evaluate("true or abs(1, 2)") is True
    assert evaluate("true and false and 1 / 0") is False
    with pytest.raises(EvalError) as left:
        evaluate("1 and false")
    assert "boolean" in str(left.value)
    with pytest.raises(EvalError):
        evaluate("1 or true")
    with pytest.raises(EvalError):
        evaluate("true and 1")
    with pytest.raises(EvalError):
        evaluate("false or 0")
    with pytest.raises(EvalError) as div:
        evaluate("true and 1 / 0")
    assert str(div.value) == "division by zero"
    with pytest.raises(EvalError):
        evaluate("not 1")
    with pytest.raises(EvalError):
        evaluate("-true")


def test_lazy_if_and_every_builtin():
    assert evaluate('if(1 < 2, "yes", 1 / 0)') == "yes"
    assert evaluate('if(false, 1 / 0, "no")') == "no"
    assert evaluate("if(false, undefined_name, 3)") == 3.0
    assert evaluate("if(true, if(false, 1, 2), 3)") == 2.0
    with pytest.raises(EvalError) as div:
        evaluate("if(true, 1 / 0, 1)")
    assert str(div.value) == "division by zero"
    with pytest.raises(EvalError):
        evaluate('if(1, "a", "b")')
    with pytest.raises(EvalError) as arity:
        evaluate('if(true, "a")')
    assert str(arity.value) == "if() takes 3 argument(s), got 2"

    assert evaluate("abs(-2.5)") == 2.5
    assert evaluate("abs(2.5)") == 2.5
    assert evaluate("min(3, 1, 2)") == 1.0
    assert evaluate("min(5)") == 5.0
    assert evaluate("max(3, 1, 4)") == 4.0
    assert evaluate("max(-1, -5, -3)") == -1.0
    assert evaluate("round(2.5)") == 2.0
    assert evaluate("round(3.5)") == 4.0
    assert evaluate("round(1.25, 1)") == 1.2
    assert evaluate("round(1.234, 2.0)") == 1.23
    assert evaluate('len("hello")') == 5.0
    assert evaluate('len("")') == 0.0
    assert type(evaluate('len("ab")')) is float
    assert evaluate('upper("Ab")') == "AB"
    assert evaluate('lower("Ab")') == "ab"
    assert evaluate("str(3.0)") == "3"
    assert evaluate("str(-4.0)") == "-4"
    assert evaluate("str(1.25)") == "1.25"
    assert evaluate("str(true)") == "true"
    assert evaluate("str(false)") == "false"
    assert evaluate('str("ab")') == "ab"
    assert evaluate('num(" 4.5 ")') == 4.5
    assert evaluate('num("1e3")') == 1000.0
    assert evaluate('num("-2.5")') == -2.5
    assert evaluate("abs(min(-3, -1))") == 3.0


def test_builtin_errors():
    with pytest.raises(EvalError) as abs_arity:
        evaluate("abs(1, 2)")
    assert str(abs_arity.value) == "abs() takes 1 argument(s), got 2"
    with pytest.raises(EvalError) as min_arity:
        evaluate("min()")
    assert str(min_arity.value) == "min() takes at least 1 argument(s), got 0"
    with pytest.raises(EvalError) as round_arity:
        evaluate("round()")
    assert str(round_arity.value) == "round() takes 1 or 2 argument(s), got 0"
    with pytest.raises(EvalError):
        evaluate('abs("x")')
    with pytest.raises(EvalError):
        evaluate("min(1, true)")
    with pytest.raises(EvalError):
        evaluate("round(1.2, 1.5)")
    with pytest.raises(EvalError):
        evaluate("round(1.2, true)")
    with pytest.raises(EvalError):
        evaluate("len(1)")
    with pytest.raises(EvalError):
        evaluate("upper(1)")
    with pytest.raises(EvalError):
        evaluate("lower(true)")
    with pytest.raises(EvalError) as bad_num:
        evaluate('num("abc")')
    assert "cannot parse" in str(bad_num.value)
    with pytest.raises(EvalError):
        evaluate('num("1.")')
    with pytest.raises(EvalError):
        evaluate("num(1)")
    with pytest.raises(EvalError):
        evaluate("str()")


def test_undefined_names_and_env_values():
    with pytest.raises(EvalError) as missing:
        evaluate("x")
    assert str(missing.value) == "undefined variable: x"
    with pytest.raises(EvalError) as missing_fn:
        evaluate("foo(1)")
    assert str(missing_fn.value) == "undefined function: foo"
    assert evaluate("x * 2", {"x": 21.0}) == 42.0
    assert evaluate("x", {"x": True}) is True
    assert evaluate('s + "!"', {"s": "hi"}) == "hi!"
    with pytest.raises(EvalError) as bad:
        evaluate("x", {"x": 2})
    assert str(bad.value) == "unsupported value for x: 2"
    with pytest.raises(EvalError) as none_value:
        evaluate("x", {"x": None})
    assert str(none_value.value) == "unsupported value for x: None"
    # A bad unused binding is not read, and a function does not fall back to a variable.
    assert evaluate("1 + 1", {"x": 2}) == 2.0
    assert evaluate("abs(-4)", {"abs": 9.0}) == 4.0
    assert evaluate("abs", {"abs": 9.0}) == 9.0
    with pytest.raises(EvalError) as not_fn:
        evaluate("x(1)", {"x": 1.0})
    assert str(not_fn.value) == "undefined function: x"


def test_env_is_not_mutated():
    env = {"x": 3.0, "s": "ab"}
    snapshot = dict(env)
    assert evaluate("x + len(s)", env) == 5.0
    assert env == snapshot
    try:
        evaluate("x / 0", env)
    except EvalError:
        pass
    assert env == snapshot
    evaluate("1", env)
    assert env == {"x": 3.0, "s": "ab"}


def test_bad_power_and_type_errors():
    with pytest.raises(EvalError):
        evaluate("(-8) ^ 0.5")
    with pytest.raises(EvalError):
        evaluate("0 ^ -1")
    with pytest.raises(EvalError):
        evaluate('1 ^ "a"')
    with pytest.raises(EvalError):
        evaluate("true - false")
    with pytest.raises(EvalError):
        evaluate("true * 2")
    with pytest.raises(EvalError):
        evaluate('"a" / "b"')
    assert evaluate("0 ^ 0") == 1.0
    assert evaluate("10 ^ 0") == 1.0


def test_acceptance_snippet():
    assert evaluate("1 + 2 * 3") == 7.0
    assert evaluate("(1 + 2) * 3") == 9.0
    assert evaluate("2 ^ 3 ^ 2") == 512.0
    assert evaluate("-2 ^ 2") == -4.0
    assert evaluate("2 ^ -1") == 0.5
    assert evaluate("7 % 3") == 1.0
    assert evaluate("-7 % 3") == 2.0
    assert evaluate('"a" + "b"') == "ab"
    assert evaluate("not 1 == 2") is True
    assert evaluate("true == 1") is False
    assert evaluate("false and 1 / 0") is False
    assert evaluate("true or 1 / 0") is True
    assert evaluate('if(1 < 2, "yes", 1 / 0)') == "yes"
    assert evaluate("x * 2", {"x": 21.0}) == 42.0
    assert evaluate('len("hello")') == 5.0
    assert evaluate("min(3, 1, 2)") == 1.0
    assert evaluate("str(3.0)") == "3"
    assert evaluate('num(" 4.5 ")') == 4.5
    assert evaluate("# just a comment\n1 + 1") == 2.0
    parse("1 / 0")
    for source in ("1 < 2 < 3", "1 2", "(1", "", "# only a comment"):
        with pytest.raises(ParseError):
            parse(source)
    for source in ('"unterminated', "1.", "1 = 2", "a @ b", '"bad \\q escape"'):
        with pytest.raises(LexError):
            tokenize(source)


def test_repl_acceptance_scenario():
    proc = run_repl('x = 2\nx * 3\n:vars\n1/0\n"a\\nb"\n:quit\n')
    assert proc.returncode == 0
    assert proc.stdout == '6\nx = 2\nerror: division by zero\n"a\\nb"\n'
    assert proc.stderr == ""


def test_repl_vars_formatting_and_eof():
    proc = run_repl('b = true\na = "hi\\n"\n:vars\n')
    assert proc.returncode == 0
    assert proc.stdout == 'a = "hi\\n"\nb = true\n'
    blank = run_repl("\n   \n4 / 2\n\n")
    assert blank.returncode == 0
    assert blank.stdout == "2\n"
    quoted = run_repl('"say \\"hi\\""\n')
    assert quoted.returncode == 0
    assert quoted.stdout == '"say \\"hi\\""\n'


def test_repl_error_preserves_env_and_quit():
    proc = run_repl("x = 5\nx = 1 / 0\n:vars\n1 = 2\n3\n")
    assert proc.returncode == 0
    assert proc.stdout == "error: division by zero\nx = 5\nerror: unexpected '='\n3\n"
    quit_proc = run_repl(":quit\n1 + 1\n")
    assert quit_proc.returncode == 0
    assert quit_proc.stdout == ""
    empty_vars = run_repl("  :vars  \n  :quit  \n")
    assert empty_vars.returncode == 0
    assert empty_vars.stdout == ""


def test_repl_assignment_and_expression_lines():
    proc = run_repl('s = "a=b"\nx=1\ny = 1 == 2\n:vars\nx + 1\n')
    assert proc.returncode == 0
    assert proc.stdout == 's = "a=b"\nx = 1\ny = false\n2\n'
    comment = run_repl("z = 4 # = 9\nz\n")
    assert comment.returncode == 0
    assert comment.stdout == "4\n"
