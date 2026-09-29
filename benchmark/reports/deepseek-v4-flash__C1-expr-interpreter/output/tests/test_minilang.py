"""Test suite for minilang expression language."""

import subprocess
import sys
from pathlib import Path

import pytest

from minilang import (
    evaluate,
    parse,
    tokenize,
    MiniLangError,
    LexError,
    ParseError,
    EvalError,
)


# ---------------------------------------------------------------------------
# Acceptance criteria (1 test per assertion group)
# ---------------------------------------------------------------------------

class TestAcceptanceCriteria:
    """All assertions from the acceptance-criteria block."""

    def test_arithmetic_precedence(self):
        assert evaluate("1 + 2 * 3") == 7.0
        assert evaluate("(1 + 2) * 3") == 9.0

    def test_power_associativity(self):
        assert evaluate("2 ^ 3 ^ 2") == 512.0

    def test_unary_minus_vs_power(self):
        assert evaluate("-2 ^ 2") == -4.0

    def test_unary_minus_power_right(self):
        assert evaluate("2 ^ -1") == 0.5

    def test_modulo(self):
        assert evaluate("7 % 3") == 1.0
        assert evaluate("-7 % 3") == 2.0

    def test_string_concatenation(self):
        assert evaluate('"a" + "b"') == "ab"

    def test_not_comparison(self):
        assert evaluate("not 1 == 2") is True

    def test_bool_vs_number_equality(self):
        assert evaluate("true == 1") is False

    def test_short_circuit_and(self):
        assert evaluate("false and 1 / 0") is False

    def test_short_circuit_or(self):
        assert evaluate("true or 1 / 0") is True

    def test_lazy_if(self):
        assert evaluate('if(1 < 2, "yes", 1 / 0)') == "yes"

    def test_env(self):
        assert evaluate("x * 2", {"x": 21.0}) == 42.0

    def test_builtin_len(self):
        assert evaluate('len("hello")') == 5.0

    def test_builtin_min(self):
        assert evaluate("min(3, 1, 2)") == 1.0

    def test_builtin_str(self):
        assert evaluate("str(3.0)") == "3"

    def test_builtin_num(self):
        assert evaluate('num(" 4.5 ")') == 4.5

    def test_comment(self):
        assert evaluate("# just a comment\n1 + 1") == 2.0

    def test_parse_no_eval(self):
        parse("1 / 0")  # must not raise

    def test_parse_error_cases(self):
        for src in ("1 < 2 < 3", "1 2", "(1", "", "# only a comment"):
            with pytest.raises(ParseError):
                parse(src)

    def test_lex_error_cases(self):
        for src in ('"unterminated', "1.", "1 = 2", "a @ b", '"bad \\q escape"'):
            with pytest.raises(LexError):
                tokenize(src)


# ---------------------------------------------------------------------------
# Tokenizer tests
# ---------------------------------------------------------------------------

class TestLexer:
    def test_number_tokens(self):
        tokens = tokenize("123 1.5 .5 1e3 1.2e-4 2E+8")
        kinds = [t.kind for t in tokens]
        assert kinds == ["NUMBER", "NUMBER", "NUMBER", "NUMBER", "NUMBER", "NUMBER"]
        # Values are raw text
        assert tokens[1].value == "1.5"
        assert tokens[2].value == ".5"
        assert tokens[5].value == "2E+8"

    def test_string_tokens(self):
        tokens = tokenize('"hello" "a\\nb" "quote\\""')
        # a\nb becomes actual newline; quote\" becomes quote"
        assert tokens[0].value == "hello"
        assert tokens[1].value == "a\nb"
        assert tokens[2].value == 'quote"'

    def test_keyword_tokens(self):
        tokens = tokenize("true false and or not")
        assert all(t.kind == "KEYWORD" for t in tokens)
        assert [t.value for t in tokens] == ["true", "false", "and", "or", "not"]

    def test_identifier_tokens(self):
        tokens = tokenize("x foo123 _bar")
        assert all(t.kind == "IDENT" for t in tokens)
        assert [t.value for t in tokens] == ["x", "foo123", "_bar"]

    def test_operator_tokens(self):
        tokens = tokenize("+ - * / % ^ == != < <= > >= ( ) ,")
        kinds = set(t.kind for t in tokens)
        assert kinds == {"OP"}
        assert len(tokens) == 15

    def test_comment_skipped(self):
        tokens = tokenize("1 # ignore this\n + 2")
        assert len(tokens) == 3  # NUMBER + OP + NUMBER
        assert tokens[0].value == "1"

    def test_lex_error_unterminated_string(self):
        with pytest.raises(LexError):
            tokenize('"hello')

    def test_lex_error_trailing_dot(self):
        with pytest.raises(LexError):
            tokenize("1.")

    def test_lex_error_single_equals(self):
        with pytest.raises(LexError):
            tokenize("1 = 2")

    def test_lex_error_bad_char(self):
        with pytest.raises(LexError):
            tokenize("@")

    def test_lex_error_bad_escape(self):
        with pytest.raises(LexError):
            tokenize('"bad \\q escape"')

    def test_token_attributes(self):
        tokens = tokenize("42")
        t = tokens[0]
        assert hasattr(t, "kind")
        assert hasattr(t, "value")
        assert hasattr(t, "position")
        assert t.kind == "NUMBER"
        assert t.value == "42"
        assert t.position == 0


# ---------------------------------------------------------------------------
# Parser tests
# ---------------------------------------------------------------------------

class TestParser:
    def test_precedence_multiplicative_over_additive(self):
        assert evaluate("2 + 3 * 4") == 14.0

    def test_precedence_comparison_over_logical(self):
        assert evaluate("true == true and false == false") is True

    def test_non_associative_comparison(self):
        with pytest.raises(ParseError):
            parse("1 < 2 < 3")

    def test_trailing_input(self):
        with pytest.raises(ParseError):
            parse("1 2")

    def test_unmatched_paren(self):
        with pytest.raises(ParseError):
            parse("(1 + 2")

    def test_empty_input(self):
        with pytest.raises(ParseError):
            parse("")

    def test_comment_only_input(self):
        with pytest.raises(ParseError):
            parse("# just a comment")

    def test_function_call_parsing(self):
        ast = parse("f(1, 2)")
        from minilang.parser import FunctionCall
        assert isinstance(ast, FunctionCall)
        assert ast.name == "f"
        assert len(ast.args) == 2

    def test_nested_parens(self):
        assert evaluate("((1 + 2) * 3)") == 9.0

    def test_right_assoc_power(self):
        assert evaluate("2 ^ 3 ^ 2") == 512.0  # 2^(3^2) = 2^9

    def test_unary_minus_precedence(self):
        assert evaluate("-2 ^ 2") == -4.0

    def test_unary_minus_right_of_power(self):
        assert evaluate("2 ^ -1") == 0.5

    def test_not_binds_looser_than_comparison(self):
        assert evaluate("not 1 == 2") is True  # not (1 == 2)

    def test_double_not(self):
        assert evaluate("not not true") is True


# ---------------------------------------------------------------------------
# Evaluator tests
# ---------------------------------------------------------------------------

class TestEvaluator:
    def test_addition_numbers(self):
        assert evaluate("1 + 2") == 3.0

    def test_subtraction(self):
        assert evaluate("5 - 3") == 2.0

    def test_multiplication(self):
        assert evaluate("3 * 4") == 12.0

    def test_division(self):
        assert evaluate("10 / 4") == 2.5

    def test_division_by_zero(self):
        with pytest.raises(EvalError, match="division by zero"):
            evaluate("1 / 0")

    def test_modulo_by_zero(self):
        with pytest.raises(EvalError, match="modulo by zero"):
            evaluate("1 % 0")

    def test_negative_modulo(self):
        assert evaluate("-7 % 3") == 2.0

    def test_power(self):
        assert evaluate("2 ^ 10") == 1024.0

    def test_power_non_real(self):
        with pytest.raises(EvalError):
            evaluate("(-8) ^ 0.5")

    def test_add_type_mismatch(self):
        with pytest.raises(EvalError):
            evaluate('1 + "a"')

    def test_compare_different_types(self):
        assert evaluate('true == 1') is False
        assert evaluate('"a" != 1') is True

    def test_compare_numbers(self):
        assert evaluate("1 < 2") is True
        assert evaluate("3 <= 3") is True
        assert evaluate("4 > 5") is False
        assert evaluate("6 >= 6") is True

    def test_compare_strings(self):
        assert evaluate('"a" < "b"') is True
        assert evaluate('"x" >= "y"') is False

    def test_compare_type_error(self):
        with pytest.raises(EvalError):
            evaluate('1 < "a"')

    def test_short_circuit_or_true(self):
        assert evaluate("true or false") is True

    def test_short_circuit_or_false(self):
        assert evaluate("false or true") is True

    def test_short_circuit_and_true(self):
        assert evaluate("true and true") is True

    def test_short_circuit_and_false(self):
        assert evaluate("true and false") is False

    def test_not_true(self):
        assert evaluate("not true") is False

    def test_not_false(self):
        assert evaluate("not false") is True

    def test_not_non_bool(self):
        with pytest.raises(EvalError):
            evaluate("not 1")

    def test_or_non_bool(self):
        with pytest.raises(EvalError):
            evaluate("1 or 2")

    def test_and_non_bool(self):
        with pytest.raises(EvalError):
            evaluate("1 and 2")

    def test_unary_minus_non_number(self):
        with pytest.raises(EvalError):
            evaluate('-"a"')

    def test_undefined_variable(self):
        with pytest.raises(EvalError, match="undefined variable: zzz"):
            evaluate("zzz")

    def test_undefined_function(self):
        with pytest.raises(EvalError, match="undefined function: nonexistent"):
            evaluate("nonexistent(1)")

    def test_env_values(self):
        assert evaluate("x + y", {"x": 10.0, "y": 5.0}) == 15.0

    def test_env_immutability(self):
        env = {"x": 1.0}
        evaluate("x + 1", env)
        assert env == {"x": 1.0}  # unchanged

    def test_env_int_rejected(self):
        with pytest.raises(EvalError, match="unsupported value for x"):
            evaluate("x", {"x": 1})  # int, not float

    def test_env_str_allowed(self):
        assert evaluate('x + "!"', {"x": "hello"}) == "hello!"

    def test_env_bool_allowed(self):
        assert evaluate("x and true", {"x": True}) is True

    def test_env_value_float(self):
        assert evaluate("x", {"x": 42.0}) == 42.0

    def test_env_value_str(self):
        assert evaluate('x', {"x": "hello"}) == "hello"

    def test_multiple_operators(self):
        assert evaluate("1 + 2 * 3 - 4 / 2") == 1 + 2 * 3 - 4 / 2

    def test_power_precedence(self):
        # ^ binds tighter than unary minus on the left
        # but -2 ^ 2 = -(2^2) = -4
        pass  # covered elsewhere

    def test_nested_function_calls(self):
        assert evaluate("round(min(1.5, 2.3))") == 2.0

    # --- Built-in function tests ---

    def test_builtin_abs(self):
        assert evaluate("abs(-3)") == 3.0
        assert evaluate("abs(5)") == 5.0

    def test_builtin_abs_arity(self):
        with pytest.raises(EvalError, match="abs\\(\\) takes 1 argument"):
            evaluate("abs(1, 2)")

    def test_builtin_min_single(self):
        assert evaluate("min(5)") == 5.0

    def test_builtin_max(self):
        assert evaluate("max(1, 9, 4)") == 9.0

    def test_builtin_round_default(self):
        assert evaluate("round(2.5)") == 2.0  # banker's rounding

    def test_builtin_round_with_n(self):
        assert evaluate("round(3.14159, 2)") == 3.14

    def test_builtin_len_string(self):
        assert evaluate('len("abc")') == 3.0

    def test_builtin_upper(self):
        assert evaluate('upper("hello")') == "HELLO"

    def test_builtin_lower(self):
        assert evaluate('lower("HELLO")') == "hello"

    def test_builtin_str_bool(self):
        assert evaluate("str(true)") == "true"
        assert evaluate("str(false)") == "false"

    def test_builtin_str_number_integral(self):
        assert evaluate("str(5.0)") == "5"

    def test_builtin_num_with_whitespace(self):
        assert evaluate('num("  3.14  ")') == 3.14

    def test_builtin_num_error(self):
        with pytest.raises(EvalError, match="cannot parse"):
            evaluate('num("abc")')

    def test_builtin_if_true(self):
        assert evaluate('if(true, "yes", "no")') == "yes"

    def test_builtin_if_false(self):
        assert evaluate('if(false, "yes", "no")') == "no"

    def test_builtin_if_arity(self):
        with pytest.raises(EvalError, match="if\\(\\) takes 3 argument"):
            evaluate("if(true, 1)")

    def test_if_condition_must_be_bool(self):
        with pytest.raises(EvalError, match="condition"):
            evaluate('if(1, "a", "b")')

    def test_builtin_arity_error(self):
        with pytest.raises(EvalError, match="len\\(\\) takes 1 argument"):
            evaluate("len(1, 2)")

    def test_function_name_not_variable(self):
            # Known built-in with wrong arity reports arity error
            with pytest.raises(EvalError, match="abs\\(\\) takes 1 argument"):
                evaluate("abs(1, 2, 3)")
            # Unknown function reports undefined function
            with pytest.raises(EvalError, match="undefined function"):
                evaluate("something(1)")

    def test_idents_and_functions_dont_cross(self):
        with pytest.raises(EvalError, match="undefined variable"):
            evaluate("abs")  # abs as variable should error


# ---------------------------------------------------------------------------
# REPL tests driven through subprocess
# ---------------------------------------------------------------------------

REPL_MODULE = "-m minilang"


class TestREPL:
    def _run_repl(self, input_lines: list[str]) -> subprocess.CompletedProcess:
        """Run the REPL with given input lines."""
        input_text = "\n".join(input_lines) + "\n"
        return subprocess.run(
            [sys.executable, "-m", "minilang"],
            input=input_text,
            capture_output=True,
            text=True,
            cwd=str(Path(__file__).resolve().parent.parent),
        )

    def test_assignment_and_vars(self):
        """Assignment prints nothing; :vars lists sorted defined variables."""
        proc = self._run_repl([
            "x = 2",
            "x * 3",
            ":vars",
            "1/0",
            '"a\\nb"',
            ":quit",
        ])
        assert proc.returncode == 0
        lines = proc.stdout.strip().splitlines()
        assert lines[0] == "6"
        assert lines[1] == "x = 2"
        assert lines[2] == "error: division by zero"
        assert lines[3] == '"a\\nb"'
        assert len(lines) == 4

    def test_empty_and_comment_lines_ignored(self):
        proc = self._run_repl([
            "",
            "  ",
            "42",
        ])
        assert proc.returncode == 0
        assert proc.stdout.strip() == "42"

    def test_quit_exits_zero(self):
        proc = self._run_repl([":quit"])
        assert proc.returncode == 0
        assert proc.stdout.strip() == ""

    def test_vars_empty(self):
        proc = self._run_repl([":vars"])
        assert proc.returncode == 0
        assert proc.stdout.strip() == ""

    def test_vars_multiple_sorted(self):
        proc = self._run_repl([
            "b = 2",
            "a = 1",
            ":vars",
            ":quit",
        ])
        lines = proc.stdout.strip().splitlines()
        assert lines[0] == "a = 1"
        assert lines[1] == "b = 2"

    def test_parse_error_in_repl(self):
        proc = self._run_repl(["1 2"])
        assert proc.returncode == 0
        assert "error:" in proc.stdout

    def test_lex_error_in_repl(self):
        proc = self._run_repl(["1."])
        assert proc.returncode == 0
        assert "error:" in proc.stdout

    def test_env_error_in_repl(self):
        proc = self._run_repl(["undefined_var"])
        assert proc.returncode == 0
        assert "error: undefined variable: undefined_var" in proc.stdout

    def test_assignment_rejected_on_error(self):
        """If assignment RHS errors, env stays unchanged and error is printed."""
        proc = self._run_repl([
            "x = 42",
            "x = 1 / 0",
            "x",
            ":quit",
        ])
        lines = proc.stdout.strip().splitlines()
        assert "error: division by zero" in lines[0]
        assert lines[1] == "42"  # x still has old value