import subprocess
import sys
from pathlib import Path

import pytest

from minilang import EvalError, LexError, ParseError, evaluate, parse, tokenize
from minilang.builtins import format_value
from minilang.lexer import Token

ROOT = Path(__file__).resolve().parents[1]


def run_repl(stdin: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "minilang"],
        input=stdin,
        capture_output=True,
        text=True,
        cwd=str(ROOT),
    )


def test_tokenize_integers_and_floats():
    toks = tokenize("123 1.5 .5")
    assert [t.kind for t in toks] == ["NUMBER", "NUMBER", "NUMBER"]
    assert toks[0].value == 123.0
    assert toks[1].value == 1.5
    assert toks[2].value == 0.5


def test_tokenize_scientific_notation():
    assert tokenize("1e3")[0].value == 1000.0
    assert tokenize("1.2e-4")[0].value == 1.2e-4
    assert tokenize("2E+8")[0].value == 2e8


def test_tokenize_string_escapes():
    tok = tokenize(r'"a\n\t\r\"\\"')[0]
    assert tok.kind == "STRING"
    assert tok.value == 'a\n\t\r"\\'


def test_tokenize_comments_and_whitespace():
    toks = tokenize("# hello\n  1 + 2  # trail")
    assert [t.kind for t in toks] == ["NUMBER", "OP", "NUMBER"]
    assert toks[1].value == "+"


def test_tokenize_keywords_vs_idents():
    toks = tokenize("true false and or not foo_1")
    assert [t.kind for t in toks] == [
        "KEYWORD",
        "KEYWORD",
        "KEYWORD",
        "KEYWORD",
        "KEYWORD",
        "IDENT",
    ]
    assert toks[-1].value == "foo_1"


def test_token_attributes_and_kinds():
    tok = tokenize("<= ")[0]
    assert isinstance(tok, Token)
    assert tok.kind == "OP"
    assert tok.value == "<="
    assert isinstance(tok.position, int)


def test_lex_errors_unterminated_trailing_dot_equals_bad_char_bad_escape():
    for src in ('"unterminated', "1.", "1 = 2", "a @ b", r'"bad \q escape"'):
        with pytest.raises(LexError):
            tokenize(src)


def test_lex_error_position_and_plain_message():
    with pytest.raises(LexError) as exc:
        tokenize("1 = 2")
    err = exc.value
    assert err.position == 2
    assert "position" not in str(err).lower()
    assert "=" in str(err) or "unexpected" in str(err)


def test_lex_error_newline_in_string():
    with pytest.raises(LexError):
        tokenize('"hello\nworld"')


def test_parse_does_not_evaluate():
    tree = parse("1 / 0")
    assert tree is not None


def test_parse_errors_comparison_trailing_unclosed_empty_comment():
    for src in ("1 < 2 < 3", "1 2", "(1", "", "# only a comment"):
        with pytest.raises(ParseError):
            parse(src)


def test_precedence_add_mul():
    assert evaluate("1 + 2 * 3") == 7.0
    assert evaluate("(1 + 2) * 3") == 9.0


def test_power_right_associative():
    assert evaluate("2 ^ 3 ^ 2") == 512.0


def test_unary_minus_looser_than_power():
    assert evaluate("-2 ^ 2") == -4.0
    assert evaluate("2 ^ -1") == 0.5


def test_and_binds_tighter_than_or():
    assert evaluate("true or false and false") is True
    assert evaluate("false and false or true") is True


def test_not_looser_than_comparison():
    assert evaluate("not 1 == 2") is True


def test_comparison_non_associative_position():
    with pytest.raises(ParseError) as exc:
        parse("1 < 2 < 3")
    assert exc.value.position is not None


def test_modulo_python_sign():
    assert evaluate("7 % 3") == 1.0
    assert evaluate("-7 % 3") == 2.0


def test_string_concat_and_number_add():
    assert evaluate('"a" + "b"') == "ab"
    assert evaluate("1.5 + 2.5") == 4.0
    with pytest.raises(EvalError):
        evaluate('1 + "a"')


def test_equality_any_types_no_coercion():
    assert evaluate("true == 1") is False
    assert evaluate("true != 1") is True
    assert evaluate('"a" == "a"') is True
    assert evaluate("1 == 1.0") is True


def test_ordering_numbers_and_strings():
    assert evaluate("1 < 2") is True
    assert evaluate('"a" < "b"') is True
    with pytest.raises(EvalError):
        evaluate('1 < "a"')
    with pytest.raises(EvalError):
        evaluate("true < false")


def test_short_circuit_and_or():
    assert evaluate("false and 1 / 0") is False
    assert evaluate("true or 1 / 0") is True
    with pytest.raises(EvalError):
        evaluate("true and 1 / 0")
    with pytest.raises(EvalError):
        evaluate("false or 1 / 0")


def test_lazy_if_builtin():
    assert evaluate('if(1 < 2, "yes", 1 / 0)') == "yes"
    assert evaluate('if(1 > 2, 1 / 0, "no")') == "no"


def test_env_lookup_and_undefined_variable():
    assert evaluate("x * 2", {"x": 21.0}) == 42.0
    with pytest.raises(EvalError) as exc:
        evaluate("missing")
    assert str(exc.value) == "undefined variable: missing"


def test_undefined_function_does_not_use_variable():
    with pytest.raises(EvalError) as exc:
        evaluate("foo(1)", {"foo": 1.0})
    assert str(exc.value) == "undefined function: foo"
    with pytest.raises(EvalError) as exc:
        evaluate("abs")
    assert str(exc.value) == "undefined variable: abs"


def test_division_by_zero_message():
    with pytest.raises(EvalError) as exc:
        evaluate("1 / 0")
    assert str(exc.value) == "division by zero"
    with pytest.raises(EvalError) as exc:
        evaluate("1 % 0")
    assert str(exc.value) == "modulo by zero"


def test_env_immutability():
    env = {"x": 1.0}
    evaluate("x + 1", env)
    assert env == {"x": 1.0}


def test_env_rejects_int_and_other_types():
    with pytest.raises(EvalError) as exc:
        evaluate("x", {"x": 2})
    assert str(exc.value).startswith("unsupported value for x:")
    with pytest.raises(EvalError):
        evaluate("x", {"x": None})


def test_every_builtin():
    assert evaluate("abs(-3)") == 3.0
    assert evaluate("min(3, 1, 2)") == 1.0
    assert evaluate("max(3, 1, 2)") == 3.0
    assert evaluate("round(2.5)") == 2.0
    assert evaluate("round(1.234, 2)") == 1.23
    assert evaluate('len("hello")') == 5.0
    assert evaluate('upper("ab")') == "AB"
    assert evaluate('lower("AB")') == "ab"
    assert evaluate("str(3.0)") == "3"
    assert evaluate("str(true)") == "true"
    assert evaluate('num(" 4.5 ")') == 4.5
    assert evaluate('if(false, 1, 2)') == 2.0


def test_builtin_arity_errors():
    with pytest.raises(EvalError) as exc:
        evaluate("abs(1, 2)")
    assert str(exc.value) == "abs() takes 1 argument(s), got 2"


def test_comment_then_expression():
    assert evaluate("# just a comment\n1 + 1") == 2.0


def test_power_non_real():
    with pytest.raises(EvalError):
        evaluate("(-8) ^ 0.5")


def test_logical_requires_booleans():
    with pytest.raises(EvalError):
        evaluate("1 and true")
    with pytest.raises(EvalError):
        evaluate("not 1")


def test_repl_assignment_vars_error_string_quit():
    result = run_repl('x = 2\nx * 3\n:vars\n1/0\n"a\\nb"\n:quit\n')
    assert result.returncode == 0
    assert result.stdout == '6\nx = 2\nerror: division by zero\n"a\\nb"\n'


def test_repl_blank_lines_and_empty_vars():
    result = run_repl("\n  \n:vars\n:quit\n")
    assert result.returncode == 0
    assert result.stdout == ""


def test_repl_error_does_not_assign():
    result = run_repl("x = 1 / 0\n:vars\nx = 3\n:vars\n:quit\n")
    assert result.returncode == 0
    assert result.stdout == "error: division by zero\nx = 3\n"


def test_format_value_bools_and_integral_numbers():
    assert format_value(True) == "true"
    assert format_value(False) == "false"
    assert format_value(512.0) == "512"
    assert format_value(-4.0) == "-4"
    assert format_value(0.5) == "0.5"


def test_parse_error_position_is_offset():
    with pytest.raises(ParseError) as exc:
        parse("1 2")
    assert exc.value.position == 2


def test_unary_and_multiplicative_chain():
    assert evaluate("8 / 2 / 2") == 2.0
    assert evaluate("2 * 3 + 4") == 10.0
    assert evaluate("--3") == 3.0
