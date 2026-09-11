"""Test suite for minilang."""

import math
import subprocess
import sys
from pathlib import Path

import pytest

from minilang import EvalError, LexError, MiniLangError, ParseError, evaluate, parse, tokenize

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def kinds_values(source):
    return [(t.kind, t.value) for t in tokenize(source)]


def run_repl(lines):
    """Run the REPL with the given input lines; return (stdout lines, exit code)."""
    proc = subprocess.run(
        [sys.executable, "-m", "minilang"],
        input="\n".join(lines) + "\n",
        cwd=str(PROJECT_ROOT),
        text=True,
        capture_output=True,
    )
    return proc.stdout.splitlines(), proc.returncode


# --------------------------------------------------------------------- lexer


def test_lex_numbers():
    assert kinds_values("123 1.5 .5 1e3 1.2e-4 2E+8") == [
        ("NUMBER", 123.0),
        ("NUMBER", 1.5),
        ("NUMBER", 0.5),
        ("NUMBER", 1000.0),
        ("NUMBER", 1.2e-4),
        ("NUMBER", 2e8),
    ]


def test_lex_bad_numbers():
    for src in ("1.", "1.e3", "1..2"):
        with pytest.raises(LexError):
            tokenize(src)


def test_lex_strings_and_escapes():
    assert kinds_values(r'"a\nb\tc\rd\"e\\f"') == [("STRING", 'a\nb\tc\rd"e\\f')]
    assert tokenize('""')[0].value == ""


def test_lex_string_errors():
    with pytest.raises(LexError):
        tokenize('"unterminated')
    with pytest.raises(LexError):
        tokenize('"bad \\q escape"')
    with pytest.raises(LexError) as info:
        tokenize('"line\nbreak"')
    assert info.value.position == 0


def test_lex_comments_are_ignored():
    assert kinds_values("1 # trailing\n+ 2") == [
        ("NUMBER", 1.0),
        ("OP", "+"),
        ("NUMBER", 2.0),
    ]
    assert tokenize("# only a comment") == []


def test_lex_keywords_identifiers_and_kinds():
    assert kinds_values("true false and or not foo _b1") == [
        ("KEYWORD", "true"),
        ("KEYWORD", "false"),
        ("KEYWORD", "and"),
        ("KEYWORD", "or"),
        ("KEYWORD", "not"),
        ("IDENT", "foo"),
        ("IDENT", "_b1"),
    ]
    assert {t.kind for t in tokenize('1 "s" x true +')} == {
        "NUMBER",
        "STRING",
        "IDENT",
        "KEYWORD",
        "OP",
    }


def test_lex_operators_and_positions():
    tokens = tokenize("+ - * / % ^ == != < <= > >= ( ) ,")
    assert all(t.kind == "OP" for t in tokens)
    assert [t.value for t in tokens] == list("+-*/%^") + [
        "==",
        "!=",
        "<",
        "<=",
        ">",
        ">=",
        "(",
        ")",
        ",",
    ]
    assert tokenize("1 + 2")[1].position == 2


def test_lex_error_positions_and_messages():
    with pytest.raises(LexError) as info:
        tokenize("1 = 2")
    assert info.value.position == 2
    assert "position" not in str(info.value)

    with pytest.raises(LexError) as info:
        tokenize("a @ b")
    assert info.value.position == 2


# -------------------------------------------------------------------- parser


def test_parse_does_not_evaluate():
    parse("1 / 0")
    parse("undefined_name + 1")


def test_parse_errors():
    for src in ("1 < 2 < 3", "1 2", "(1", "", "# only a comment", "1 +", "f(1,)"):
        with pytest.raises(ParseError):
            parse(src)


def test_parse_error_position():
    with pytest.raises(ParseError) as info:
        parse("1 2")
    assert info.value.position == 2
    with pytest.raises(ParseError) as info:
        parse("")
    assert info.value.position == 0


# ---------------------------------------------------------------- precedence


def test_precedence_arithmetic():
    assert evaluate("1 + 2 * 3") == 7.0
    assert evaluate("(1 + 2) * 3") == 9.0
    assert evaluate("10 - 2 - 3") == 5.0
    assert evaluate("100 / 10 / 2") == 5.0
    assert evaluate("1 + 8 % 3") == 3.0


def test_precedence_full_ladder():
    # or < and < not < comparison < additive < multiplicative < unary < ^
    assert evaluate("true or false and false") is True
    assert evaluate("not 1 + 1 == 2") is False
    assert evaluate("1 + 2 * 3 ^ 2 < 20 and true") is True
    assert evaluate("1 + 2 * 3 ^ 2") == 19.0
    assert evaluate("1 + 2 * 3 ^ 2 < 19 or false") is False
    assert evaluate("false or 2 ^ 2 == 4") is True


def test_power_right_associative():
    assert evaluate("2 ^ 3 ^ 2") == 512.0
    assert evaluate("2 ^ -1") == 0.5


def test_unary_minus_looser_than_power():
    assert evaluate("-2 ^ 2") == -4.0
    assert evaluate("(-2) ^ 2") == 4.0
    assert evaluate("- - 3") == 3.0


def test_not_looser_than_comparison():
    assert evaluate("not 1 == 2") is True
    assert evaluate("not 2 == 2") is False


def test_comparison_non_associative():
    with pytest.raises(ParseError):
        parse("1 < 2 < 3")
    with pytest.raises(ParseError):
        parse("1 == 2 != 3")


# ----------------------------------------------------------------- semantics


def test_plus_rules():
    assert evaluate('"a" + "b"') == "ab"
    assert evaluate("1 + 2") == 3.0
    with pytest.raises(EvalError):
        evaluate('1 + "a"')
    with pytest.raises(EvalError):
        evaluate("true + true")


def test_modulo_and_division():
    assert evaluate("7 % 3") == 1.0
    assert evaluate("-7 % 3") == 2.0
    assert evaluate("7 % -3") == -2.0
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
        evaluate('"a" ^ 2')


def test_equality_across_types():
    assert evaluate("true == 1") is False
    assert evaluate("true != 1") is True
    assert evaluate('"1" == 1') is False
    assert evaluate("1 == 1") is True
    assert evaluate('"a" == "a"') is True
    assert evaluate("true == true") is True


def test_ordering_requires_matching_types():
    assert evaluate('"abc" < "abd"') is True
    assert evaluate("2 >= 2") is True
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
        evaluate("1 and true")
    with pytest.raises(EvalError):
        evaluate("true and 1")


def test_not_and_unary_minus_type_checks():
    assert evaluate("not false") is True
    with pytest.raises(EvalError):
        evaluate("not 1")
    with pytest.raises(EvalError):
        evaluate('-"a"')


def test_no_implicit_truthiness():
    with pytest.raises(EvalError):
        evaluate('if("", 1, 2)')
    with pytest.raises(EvalError):
        evaluate("0 or true")


# --------------------------------------------------------------- environment


def test_variables_and_undefined_names():
    assert evaluate("x * 2", {"x": 21.0}) == 42.0
    with pytest.raises(EvalError) as info:
        evaluate("nope + 1")
    assert str(info.value) == "undefined variable: nope"
    assert info.value.position is None


def test_undefined_function_and_disjoint_namespaces():
    with pytest.raises(EvalError) as info:
        evaluate("nope(1)")
    assert str(info.value) == "undefined function: nope"
    with pytest.raises(EvalError) as info:
        evaluate("x(1)", {"x": 2.0})
    assert str(info.value) == "undefined function: x"
    with pytest.raises(EvalError) as info:
        evaluate("abs + 1")
    assert str(info.value) == "undefined variable: abs"


def test_env_is_not_mutated():
    env = {"x": 1.0}
    snapshot = dict(env)
    assert evaluate("x + 1", env) == 2.0
    assert env == snapshot
    assert evaluate("x", env) == 1.0


def test_unsupported_env_values():
    with pytest.raises(EvalError) as info:
        evaluate("x", {"x": 2})
    assert str(info.value) == "unsupported value for x: 2"
    with pytest.raises(EvalError):
        evaluate("y", {"y": [1]})
    # Bad values are only rejected when actually read.
    assert evaluate("1 + 1", {"bad": None}) == 2.0


# ------------------------------------------------------------------ builtins


def test_builtin_abs_min_max():
    assert evaluate("abs(-3)") == 3.0
    assert evaluate("min(3, 1, 2)") == 1.0
    assert evaluate("max(3, 1, 2)") == 3.0
    assert evaluate("min(5)") == 5.0
    assert isinstance(evaluate("abs(-3)"), float)
    with pytest.raises(EvalError) as info:
        evaluate("abs(1, 2)")
    assert str(info.value) == "abs() takes 1 argument(s), got 2"
    with pytest.raises(EvalError):
        evaluate('min(1, "a")')
    with pytest.raises(EvalError):
        evaluate("max()")


def test_builtin_round():
    assert evaluate("round(2.5)") == 2.0  # banker's rounding
    assert evaluate("round(3.5)") == 4.0
    assert evaluate("round(1.2345, 2)") == 1.23
    assert isinstance(evaluate("round(1.5)"), float)
    with pytest.raises(EvalError):
        evaluate("round(1.5, 0.5)")
    with pytest.raises(EvalError):
        evaluate("round()")


def test_builtin_string_functions():
    assert evaluate('len("hello")') == 5.0
    assert isinstance(evaluate('len("ab")'), float)
    assert evaluate('upper("aB")') == "AB"
    assert evaluate('lower("aB")') == "ab"
    with pytest.raises(EvalError):
        evaluate("len(1)")
    with pytest.raises(EvalError):
        evaluate("upper(1)")
    with pytest.raises(EvalError):
        evaluate('lower("a", "b")')


def test_builtin_str_and_num():
    assert evaluate("str(3.0)") == "3"
    assert evaluate("str(1.25)") == "1.25"
    assert evaluate("str(true)") == "true"
    assert evaluate("str(false)") == "false"
    assert evaluate('str("hi")') == "hi"
    assert evaluate('num(" 4.5 ")') == 4.5
    assert evaluate('num("1e3")') == 1000.0
    with pytest.raises(EvalError):
        evaluate('num("abc")')
    with pytest.raises(EvalError):
        evaluate("num(1)")


def test_builtin_if_is_lazy():
    assert evaluate('if(1 < 2, "yes", 1 / 0)') == "yes"
    assert evaluate("if(false, 1 / 0, 9)") == 9.0
    with pytest.raises(EvalError) as info:
        evaluate("if(true, 1)")
    assert str(info.value) == "if() takes 3 argument(s), got 2"
    with pytest.raises(EvalError):
        evaluate("if(1, 2, 3)")


# --------------------------------------------------------------------- misc


def test_comments_and_whitespace_in_evaluate():
    assert evaluate("# just a comment\n1 + 1") == 2.0
    assert evaluate("\t1\n  +\n2 # done") == 3.0


def test_error_hierarchy_and_str():
    assert issubclass(LexError, MiniLangError)
    assert issubclass(ParseError, MiniLangError)
    assert issubclass(EvalError, MiniLangError)
    error = EvalError("boom")
    assert str(error) == "boom"
    assert error.position is None


def test_every_number_is_a_float():
    for src in ('len("ab")', "1 + 1", "abs(-1)", "round(1.4)", "min(1, 2)", "2 ^ 2"):
        assert type(evaluate(src)) is float
    assert not math.isnan(evaluate("1 / 3"))


def test_public_api_surface():
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
    for name in minilang.__all__:
        assert hasattr(minilang, name)


# --------------------------------------------------------------------- REPL


def test_repl_acceptance_scenario():
    lines, code = run_repl(["x = 2", "x * 3", ":vars", "1/0", r'"a\nb"', ":quit"])
    assert lines == ["6", "x = 2", "error: division by zero", r'"a\nb"']
    assert code == 0


def test_repl_blank_lines_vars_and_eof():
    lines, code = run_repl(["", "   ", ":vars", "a = 1.5", "b = \"hi\"", ":vars"])
    assert lines == ["a = 1.5", 'b = "hi"']
    assert code == 0


def test_repl_errors_leave_env_unchanged():
    lines, code = run_repl(["x = 1", "x = 1 / 0", "x", "y", "x = x + 1", "x"])
    assert lines == ["error: division by zero", "1", "error: undefined variable: y", "2"]
    assert code == 0


def test_repl_quit_stops_processing():
    lines, code = run_repl(["1 + 1", ":quit", "2 + 2"])
    assert lines == ["2"]
    assert code == 0


def test_repl_formats_booleans_and_strings():
    lines, code = run_repl(['1 < 2', 'not true', r'"q\"\\t"', "0.5", "-4.0"])
    assert lines == ["true", "false", r'"q\"\\t"', "0.5", "-4"]
    assert code == 0
