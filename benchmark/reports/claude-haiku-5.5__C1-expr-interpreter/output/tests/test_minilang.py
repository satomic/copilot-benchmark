import math
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from minilang import EvalError, LexError, ParseError, evaluate, parse, tokenize  # noqa: E402
from minilang.builtins import format_value  # noqa: E402


def run_repl(text):
    return subprocess.run(
        [sys.executable, "-m", "minilang"],
        input=text,
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=ROOT,
        timeout=30,
    )


def test_numbers_lex_as_floats():
    toks = tokenize("123 1.5 .5 1e3 1.2e-4 2E+8")
    assert [t.kind for t in toks] == ["NUMBER"] * 6
    assert [t.value for t in toks] == [123.0, 1.5, 0.5, 1000.0, 1.2e-4, 2e8]
    assert all(isinstance(t.value, float) for t in toks)


def test_trailing_dot_is_lex_error_with_position():
    with pytest.raises(LexError) as info:
        tokenize("1.")
    assert info.value.position == 1


def test_string_escapes():
    assert evaluate(r'"a\nb\t\r\"\\"') == 'a\nb\t\r"\\'


def test_invalid_escape_and_unterminated_string():
    with pytest.raises(LexError):
        tokenize(r'"bad \q escape"')
    with pytest.raises(LexError):
        tokenize('"unterminated')
    with pytest.raises(LexError):
        tokenize('"line\nbreak"')


def test_keywords_and_identifiers():
    kinds = [t.kind for t in tokenize("and or not true false abc _x1")]
    assert kinds == ["KEYWORD"] * 5 + ["IDENT"] * 2


def test_single_equals_and_unknown_characters_are_lex_errors():
    with pytest.raises(LexError) as info:
        tokenize("1 = 2")
    assert info.value.position == 2
    with pytest.raises(LexError):
        tokenize("a @ b")


def test_comments_are_skipped():
    assert evaluate("# just a comment\n1 + 1") == 2.0
    assert evaluate("1 + 1 # trailing") == 2.0


def test_precedence_levels():
    assert evaluate("1 + 2 * 3") == 7.0
    assert evaluate("(1 + 2) * 3") == 9.0
    assert evaluate("1 - 2 - 3") == -4.0
    assert evaluate("8 / 4 / 2") == 1.0
    assert evaluate("not 1 == 2") is True
    assert evaluate("true or false and false") is True


def test_power_is_right_associative_and_binds_tighter_than_unary_minus():
    assert evaluate("2 ^ 3 ^ 2") == 512.0
    assert evaluate("-2 ^ 2") == -4.0
    assert evaluate("2 ^ -1") == 0.5


def test_modulo_follows_python_sign_rules():
    assert evaluate("7 % 3") == 1.0
    assert evaluate("-7 % 3") == 2.0


def test_comparison_is_non_associative():
    with pytest.raises(ParseError):
        parse("1 < 2 < 3")


@pytest.mark.parametrize("src", ["1 2", "(1", "", "# only a comment", "f(1,)"])
def test_parse_errors(src):
    with pytest.raises(ParseError):
        parse(src)


def test_parse_does_not_evaluate():
    parse("1 / 0")


def test_string_concat_and_type_errors():
    assert evaluate('"a" + "b"') == "ab"
    with pytest.raises(EvalError):
        evaluate('"a" + 1')
    with pytest.raises(EvalError):
        evaluate("true - 1")


def test_equality_never_errors_and_is_type_strict():
    assert evaluate("true == 1") is False
    assert evaluate('"1" == 1') is False
    assert evaluate('"a" != "b"') is True


def test_ordering_requires_matching_types():
    assert evaluate('"abc" < "abd"') is True
    with pytest.raises(EvalError):
        evaluate('1 < "2"')


def test_division_and_modulo_by_zero():
    with pytest.raises(EvalError, match="^division by zero$"):
        evaluate("1 / 0")
    with pytest.raises(EvalError, match="^modulo by zero$"):
        evaluate("1 % 0")


def test_power_non_real_result_is_error():
    with pytest.raises(EvalError):
        evaluate("(-8) ^ 0.5")


def test_short_circuit_and_or():
    assert evaluate("false and (1 / 0)") is False
    assert evaluate("true or (1 / 0)") is True
    with pytest.raises(EvalError):
        evaluate("1 and true")
    with pytest.raises(EvalError):
        evaluate("true and 1")


def test_not_and_unary_minus_require_correct_types():
    with pytest.raises(EvalError):
        evaluate("not 1")
    with pytest.raises(EvalError):
        evaluate('-"a"')


def test_lazy_if_only_evaluates_taken_branch():
    assert evaluate('if(1 < 2, "yes", 1 / 0)') == "yes"
    assert evaluate("if(false, 1 / 0, 7)") == 7.0
    with pytest.raises(EvalError):
        evaluate("if(1, 2, 3)")


def test_undefined_variable_and_function():
    with pytest.raises(EvalError, match="^undefined variable: y$"):
        evaluate("y + 1")
    with pytest.raises(EvalError, match="^undefined function: foo$"):
        evaluate("foo(1)")
    # a name used as a function does not fall back to a variable
    with pytest.raises(EvalError, match="^undefined function: x$"):
        evaluate("x(1)", {"x": 1.0})


def test_env_values_and_immutability():
    env = {"x": 21.0, "s": "hi", "b": True}
    assert evaluate("x * 2", env) == 42.0
    assert env == {"x": 21.0, "s": "hi", "b": True}
    with pytest.raises(EvalError, match="^unsupported value for n: 2$"):
        evaluate("n", {"n": 2})


def test_arity_error_message():
    with pytest.raises(EvalError, match=r"^abs\(\) takes 1 argument\(s\), got 2$"):
        evaluate("abs(1, 2)")


def test_builtin_abs_min_max_round():
    assert evaluate("abs(-3)") == 3.0
    assert evaluate("min(3, 1, 2)") == 1.0
    assert evaluate("max(3, 1, 2)") == 3.0
    assert evaluate("round(2.5)") == 2.0  # banker's rounding
    assert evaluate("round(1.2345, 2)") == 1.23
    with pytest.raises(EvalError):
        evaluate("round(1.5, 1.5)")
    with pytest.raises(EvalError):
        evaluate("min()")


def test_builtin_string_functions():
    assert evaluate('len("hello")') == 5.0
    assert evaluate('upper("aB")') == "AB"
    assert evaluate('lower("aB")') == "ab"
    with pytest.raises(EvalError):
        evaluate("len(3)")


def test_builtin_str_and_num():
    assert evaluate("str(3.0)") == "3"
    assert evaluate("str(0.5)") == "0.5"
    assert evaluate("str(true)") == "true"
    assert evaluate('num(" 4.5 ")') == 4.5
    with pytest.raises(EvalError):
        evaluate('num("abc")')
    with pytest.raises(EvalError):
        evaluate('num("inf")')


def test_format_value():
    assert format_value(512.0) == "512"
    assert format_value(1.25) == "1.25"
    assert format_value(True) == "true"
    assert format_value("a\nb") == '"a\\nb"'


def test_repl_acceptance_session():
    result = run_repl('x = 2\nx * 3\n:vars\n1/0\n"a\\nb"\n:quit\n')
    assert result.returncode == 0
    assert result.stdout == '6\nx = 2\nerror: division by zero\n"a\\nb"\n'


def test_repl_errors_do_not_change_environment():
    result = run_repl("a = 1\nb = a / 0\nb\n:vars\n")
    assert result.returncode == 0
    assert result.stdout == (
        "error: division by zero\nerror: undefined variable: b\na = 1\n"
    )


def test_repl_blank_lines_and_eof_exit_zero():
    result = run_repl("\n   \n1 + 1\n")
    assert result.returncode == 0
    assert result.stdout == "2\n"


def test_repl_quit_stops_processing():
    result = run_repl(":quit\n1 + 1\n")
    assert result.returncode == 0
    assert result.stdout == ""


def test_repl_formats_booleans_and_strings():
    result = run_repl('s = "hi"\nflag = 1 < 2\nflag\ns + "!"\n:vars\n')
    assert result.returncode == 0
    assert result.stdout == 'true\n"hi!"\nflag = true\ns = "hi"\n'
