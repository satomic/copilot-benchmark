import pytest
import subprocess
import sys
from minilang import evaluate, parse, tokenize, EvalError, LexError, ParseError


class TestLexer:
    def test_tokenize_number(self):
        tokens = tokenize("123")
        assert len(tokens) == 1
        assert tokens[0].kind == "NUMBER"
        assert tokens[0].value == 123.0
    
    def test_tokenize_float(self):
        tokens = tokenize("1.5")
        assert tokens[0].value == 1.5
    
    def test_tokenize_dot_number(self):
        tokens = tokenize(".5")
        assert tokens[0].value == 0.5
    
    def test_tokenize_scientific(self):
        tokens = tokenize("1e3")
        assert tokens[0].value == 1000.0
    
    def test_tokenize_string(self):
        tokens = tokenize('"hello"')
        assert tokens[0].kind == "STRING"
        assert tokens[0].value == "hello"
    
    def test_tokenize_string_escape_n(self):
        tokens = tokenize('"a\\nb"')
        assert tokens[0].value == "a\nb"
    
    def test_tokenize_string_escape_quote(self):
        tokens = tokenize('"say \\"hi\\""')
        assert tokens[0].value == 'say "hi"'
    
    def test_tokenize_comment(self):
        tokens = tokenize("# comment\n123")
        assert len(tokens) == 1
    
    def test_tokenize_ident(self):
        tokens = tokenize("abc")
        assert tokens[0].kind == "IDENT"
        assert tokens[0].value == "abc"
    
    def test_tokenize_keyword_true(self):
        tokens = tokenize("true")
        assert tokens[0].kind == "KEYWORD"
        assert tokens[0].value is True
    
    def test_tokenize_keyword_false(self):
        tokens = tokenize("false")
        assert tokens[0].kind == "KEYWORD"
        assert tokens[0].value is False
    
    def test_tokenize_operator(self):
        tokens = tokenize("+ - * / %")
        assert len(tokens) == 5
        assert all(t.kind == "OP" for t in tokens)
    
    def test_lex_error_unterminated_string(self):
        with pytest.raises(LexError):
            tokenize('"unterminated')
    
    def test_lex_error_dot_number(self):
        with pytest.raises(LexError):
            tokenize("1.")
    
    def test_lex_error_single_equals(self):
        with pytest.raises(LexError):
            tokenize("1 = 2")
    
    def test_lex_error_bad_escape(self):
        with pytest.raises(LexError):
            tokenize('"bad \\q escape"')


class TestParser:
    def test_parse_number(self):
        ast = parse("123")
        assert ast.value == 123.0
    
    def test_parse_binop(self):
        ast = parse("1 + 2")
        assert ast.op == "+"
    
    def test_parse_precedence_add_mul(self):
        ast = parse("1 + 2 * 3")
        assert ast.op == "+"
        assert ast.right.op == "*"
    
    def test_parse_power_right_assoc(self):
        ast = parse("2 ^ 3 ^ 2")
        assert ast.op == "^"
        assert ast.right.op == "^"
    
    def test_parse_unary_minus(self):
        ast = parse("-2")
        assert ast.op == "-"
    
    def test_parse_unary_minus_power(self):
        ast = parse("-2 ^ 2")
        assert ast.op == "-"
        assert ast.operand.op == "^"
    
    def test_parse_power_right_operand_unary(self):
        ast = parse("2 ^ -1")
        assert ast.op == "^"
        assert ast.right.op == "-"
    
    def test_parse_not(self):
        ast = parse("not true")
        assert ast.op == "not"
    
    def test_parse_comparison_non_associative(self):
        with pytest.raises(ParseError):
            parse("1 < 2 < 3")
    
    def test_parse_trailing_input(self):
        with pytest.raises(ParseError):
            parse("1 2")
    
    def test_parse_empty(self):
        with pytest.raises(ParseError):
            parse("")
    
    def test_parse_comment_only(self):
        with pytest.raises(ParseError):
            parse("# comment")
    
    def test_parse_no_eval_div_zero(self):
        ast = parse("1 / 0")
        assert ast is not None


class TestEvaluator:
    def test_eval_number(self):
        assert evaluate("123") == 123.0
    
    def test_eval_string(self):
        assert evaluate('"hello"') == "hello"
    
    def test_eval_add(self):
        assert evaluate("1 + 2 * 3") == 7.0
    
    def test_eval_parens(self):
        assert evaluate("(1 + 2) * 3") == 9.0
    
    def test_eval_power_right_assoc(self):
        assert evaluate("2 ^ 3 ^ 2") == 512.0
    
    def test_eval_unary_minus_power(self):
        assert evaluate("-2 ^ 2") == -4.0
    
    def test_eval_power_negative_exp(self):
        assert evaluate("2 ^ -1") == 0.5
    
    def test_eval_modulo(self):
        assert evaluate("7 % 3") == 1.0
    
    def test_eval_modulo_negative(self):
        assert evaluate("-7 % 3") == 2.0
    
    def test_eval_string_concat(self):
        assert evaluate('"a" + "b"') == "ab"
    
    def test_eval_comparison(self):
        assert evaluate("not 1 == 2") is True
    
    def test_eval_equality_different_types(self):
        assert evaluate("true == 1") is False
    
    def test_eval_short_circuit_and(self):
        assert evaluate("false and 1 / 0") is False
    
    def test_eval_short_circuit_or(self):
        assert evaluate("true or 1 / 0") is True
    
    def test_eval_if_true(self):
        assert evaluate('if(1 < 2, "yes", 1 / 0)') == "yes"
    
    def test_eval_if_false(self):
        assert evaluate('if(false, 1 / 0, "no")') == "no"
    
    def test_eval_env(self):
        assert evaluate("x * 2", {"x": 21.0}) == 42.0
    
    def test_eval_len(self):
        assert evaluate('len("hello")') == 5.0
    
    def test_eval_min(self):
        assert evaluate("min(3, 1, 2)") == 1.0
    
    def test_eval_max(self):
        assert evaluate("max(3, 1, 2)") == 3.0
    
    def test_eval_str_number(self):
        assert evaluate('str(3.0)') == "3"
    
    def test_eval_str_bool(self):
        assert evaluate('str(true)') == "true"
    
    def test_eval_num(self):
        assert evaluate('num(" 4.5 ")') == 4.5
    
    def test_eval_abs(self):
        assert evaluate('abs(-5)') == 5.0
    
    def test_eval_round(self):
        assert evaluate('round(3.7)') == 4.0
    
    def test_eval_upper(self):
        assert evaluate('upper("hello")') == "HELLO"
    
    def test_eval_lower(self):
        assert evaluate('lower("HELLO")') == "hello"
    
    def test_eval_div_zero(self):
        with pytest.raises(EvalError, match="division by zero"):
            evaluate("1 / 0")
    
    def test_eval_mod_zero(self):
        with pytest.raises(EvalError, match="modulo by zero"):
            evaluate("7 % 0")
    
    def test_eval_undefined_var(self):
        with pytest.raises(EvalError, match="undefined variable"):
            evaluate("x")
    
    def test_eval_undefined_func(self):
        with pytest.raises(EvalError, match="undefined function"):
            evaluate("foo()")
    
    def test_eval_env_immutable(self):
        env = {"x": 1.0}
        evaluate("x + 1", env)
        assert env == {"x": 1.0}
    
    def test_eval_comment_in_expr(self):
        assert evaluate("# comment\n1 + 1") == 2.0
    
    def test_eval_not_type_mismatch(self):
        with pytest.raises(EvalError):
            evaluate("not 1")
    
    def test_eval_and_requires_bool(self):
        with pytest.raises(EvalError):
            evaluate("1 and true")


class TestREPL:
    def test_repl_basic_expression(self):
        result = subprocess.run(
            [sys.executable, "-m", "minilang"],
            input="1 + 2\n:quit\n",
            capture_output=True,
            text=True,
        )
        assert result.stdout == "3\n"
        assert result.returncode == 0
    
    def test_repl_assignment_and_usage(self):
        result = subprocess.run(
            [sys.executable, "-m", "minilang"],
            input="x = 2\nx * 3\n:quit\n",
            capture_output=True,
            text=True,
        )
        assert result.stdout == "6\n"
        assert result.returncode == 0
    
    def test_repl_vars(self):
        result = subprocess.run(
            [sys.executable, "-m", "minilang"],
            input="x = 2\n:vars\n:quit\n",
            capture_output=True,
            text=True,
        )
        assert result.stdout == "x = 2\n"
        assert result.returncode == 0
    
    def test_repl_error_handling(self):
        result = subprocess.run(
            [sys.executable, "-m", "minilang"],
            input="1/0\n:quit\n",
            capture_output=True,
            text=True,
        )
        assert "error:" in result.stdout
        assert result.returncode == 0
    
    def test_repl_string_escape_display(self):
        result = subprocess.run(
            [sys.executable, "-m", "minilang"],
            input='"a\\nb"\n:quit\n',
            capture_output=True,
            text=True,
        )
        assert result.stdout == '"a\\nb"\n'
        assert result.returncode == 0
