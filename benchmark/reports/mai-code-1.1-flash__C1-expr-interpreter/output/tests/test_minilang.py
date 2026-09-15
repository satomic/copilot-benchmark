import subprocess
import sys

import pytest

from minilang import EvalError, LexError, ParseError, evaluate, parse, tokenize


def test_tokenize_number_and_string_values():
    tokens = tokenize('123 1.5 .5 1e3 "hi"')
    assert [(t.kind, t.value, t.position) for t in tokens] == [
        ("NUMBER", 123.0, 0),
        ("NUMBER", 1.5, 4),
        ("NUMBER", 0.5, 8),
        ("NUMBER", 1000.0, 11),
        ("STRING", "hi", 15),
    ]


def test_tokenize_string_escapes():
    tokens = tokenize('"a\\n\\t\\r\\\\\\\""')
    assert tokens[0].kind == "STRING"
    assert tokens[0].value == 'a\n\t\r\\"'


def test_tokenize_comment_ignored():
    tokens = tokenize('# hello\n1 + 2 # more\n')
    assert [(t.kind, t.value) for t in tokens] == [("NUMBER", 1.0), ("OP", "+"), ("NUMBER", 2.0)]


def test_tokenize_keywords_and_idents():
    tokens = tokenize('true false and or not foo_bar')
    assert [t.kind for t in tokens] == ["KEYWORD", "KEYWORD", "KEYWORD", "KEYWORD", "KEYWORD", "IDENT"]
    assert [t.value for t in tokens] == ["true", "false", "and", "or", "not", "foo_bar"]


def test_tokenize_invalid_single_equals():
    with pytest.raises(LexError):
        tokenize('1 = 2')


def test_tokenize_invalid_character():
    with pytest.raises(LexError):
        tokenize('a @ b')


def test_tokenize_unterminated_string():
    with pytest.raises(LexError):
        tokenize('"unterminated')


def test_parse_or_and_precedence():
    assert evaluate('true or false and false') is True
    assert evaluate('false and true or true') is True


def test_parse_not_lower_than_comparison():
    assert evaluate('not 1 == 2') is True
    assert evaluate('not 1 < 2') is False


def test_parse_additive_and_multiplicative_precedence():
    assert evaluate('1 + 2 * 3') == 7.0
    assert evaluate('(1 + 2) * 3') == 9.0
    assert evaluate('8 / 2 + 1') == 5.0


def test_parse_power_right_associative():
    assert evaluate('2 ^ 3 ^ 2') == 512.0


def test_parse_unary_minus_looser_than_power():
    assert evaluate('-2 ^ 2') == -4.0
    assert evaluate('2 ^ -1') == 0.5


def test_parse_non_associative_comparison_raises():
    with pytest.raises(ParseError):
        parse('1 < 2 < 3')


def test_parse_trailing_input_raises():
    with pytest.raises(ParseError):
        parse('1 2')


def test_parse_empty_or_comment_only_raises():
    for src in ('', '# just a comment'):
        with pytest.raises(ParseError):
            parse(src)


def test_evaluate_number_math():
    assert evaluate('7 % 3') == 1.0
    assert evaluate('-7 % 3') == 2.0
    assert evaluate('3 - 2 * 4') == -5.0


def test_evaluate_string_concat_and_comparison():
    assert evaluate('"a" + "b"') == 'ab'
    assert evaluate('"a" < "b"') is True
    assert evaluate('"b" >= "a"') is True


def test_evaluate_bool_ops_and_equality_types():
    assert evaluate('true == 1') is False
    assert evaluate('true != 1') is True
    assert evaluate('false and 1 / 0') is False
    assert evaluate('true or 1 / 0') is True


def test_short_circuit_left_operand_must_be_boolean():
    with pytest.raises(EvalError):
        evaluate('1 and true')


def test_lazy_if_builtin():
    assert evaluate('if(1 < 2, "yes", 1 / 0)') == 'yes'
    assert evaluate('if(false, 1 / 0, "no")') == 'no'


def test_builtin_abs_min_max_round():
    assert evaluate('abs(-3.5)') == 3.5
    assert evaluate('min(3, 1, 2)') == 1.0
    assert evaluate('max(3, 1, 2)') == 3.0
    assert evaluate('round(2.5)') == 2.0
    assert evaluate('round(2.5, 0)') == 2.0
    assert evaluate('round(2.5, 1)') == 2.5


def test_builtin_len_upper_lower():
    assert evaluate('len("hello")') == 5.0
    assert evaluate('upper("ab")') == 'AB'
    assert evaluate('lower("XY")') == 'xy'


def test_builtin_str_and_num():
    assert evaluate('str(3.0)') == '3'
    assert evaluate('num(" 4.5 ")') == 4.5
    with pytest.raises(EvalError):
        evaluate('num("abc")')


def test_builtin_arity_and_type_errors():
    with pytest.raises(EvalError):
        evaluate('abs()')
    with pytest.raises(EvalError):
        evaluate('len(3)')
    with pytest.raises(EvalError):
        evaluate('min()')


def test_undefined_variable():
    with pytest.raises(EvalError, match='undefined variable: x'):
        evaluate('x * 2')


def test_undefined_function():
    with pytest.raises(EvalError, match='undefined function: foo'):
        evaluate('foo(1)')


def test_division_by_zero_and_modulo_zero():
    with pytest.raises(EvalError, match='division by zero'):
        evaluate('1 / 0')
    with pytest.raises(EvalError, match='modulo by zero'):
        evaluate('1 % 0')


def test_env_immutability():
    env = {'x': 21.0}
    result = evaluate('x * 2', env)
    assert result == 42.0
    assert env == {'x': 21.0}


def test_unsupported_env_value_raises_when_read():
    env = {'x': 2}
    with pytest.raises(EvalError, match='unsupported value for x: 2'):
        evaluate('x + 1', env)


def test_repl_simple_assignment_and_vars_and_quit():
    result = subprocess.run(
        [sys.executable, '-m', 'minilang'],
        input='x = 2\nx * 3\n:vars\n:quit\n',
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0
    assert result.stdout == '6\nx = 2\n'


def test_repl_error_continues_and_prints_string_escape():
    result = subprocess.run(
        [sys.executable, '-m', 'minilang'],
        input='1/0\n"a\\n b"\n:quit\n',
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0
    assert 'error: division by zero' in result.stdout
    assert '"a\\n b"' in result.stdout


def test_repl_ignores_blank_lines_and_handles_assignment_error():
    result = subprocess.run(
        [sys.executable, '-m', 'minilang'],
        input='\nfoo = 1\nfoo + 2\n:quit\n',
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0
    assert result.stdout == '3\n'


def test_repl_does_not_print_prompt_or_banner():
    result = subprocess.run(
        [sys.executable, '-m', 'minilang'],
        input='1\n:quit\n',
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.stdout == '1\n'


def test_parse_rejects_bad_number_ending_dot():
    with pytest.raises(LexError):
        tokenize('1.')


def test_eval_unary_minus_and_not():
    assert evaluate('-3') == -3.0
    assert evaluate('not false') is True
    assert evaluate('not true') is False


def test_compare_strings_lexicographic_and_non_numbers_error():
    assert evaluate('"a" <= "b"') is True
    with pytest.raises(EvalError):
        evaluate('1 < "a"')


def test_power_with_negative_base_and_fractional_exp_rejected():
    with pytest.raises(EvalError):
        evaluate('(-8) ^ 0.5')
