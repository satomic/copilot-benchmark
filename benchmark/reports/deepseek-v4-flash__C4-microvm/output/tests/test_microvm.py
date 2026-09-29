import subprocess
import sys
import zlib

import pytest

import microvm
import microvm.errors
import microvm.parser as parser_mod
import microvm.lexer as lexer_mod
import microvm.optimizer as optimizer_mod


# ---- Lexer tests ----

class TestLexer:
    def test_lexer_int(self) -> None:
        toks = microvm.tokenize("123")
        assert len(toks) == 1
        assert toks[0].kind == "INT"
        assert toks[0].value == 123

    def test_lexer_float(self) -> None:
        toks = microvm.tokenize("3.14")
        assert toks[0].kind == "FLOAT"
        assert toks[0].value == 3.14

    def test_lexer_string(self) -> None:
        toks = microvm.tokenize('"hello"')
        assert toks[0].kind == "STRING"
        assert toks[0].value == "hello"

    def test_lexer_escapes(self) -> None:
        toks = microvm.tokenize('"a\\nb\\tc\\\"d\\\\e"')
        assert toks[0].value == "a\nb\tc\"d\\e"

    def test_lexer_unterminated_string(self) -> None:
        with pytest.raises(microvm.errors.LexError):
            microvm.tokenize('"hello')

    def test_lexer_invalid_float_dot_start(self) -> None:
        with pytest.raises(microvm.errors.LexError):
            microvm.tokenize(".5")

    def test_lexer_invalid_float_dot_end(self) -> None:
        with pytest.raises(microvm.errors.LexError):
            microvm.tokenize("1.")

    def test_lexer_float_exponent(self) -> None:
        toks = microvm.tokenize("1.5e3")
        assert toks[0].kind == "FLOAT"
        assert toks[0].value == 1500.0

    def test_lexer_keyword(self) -> None:
        toks = microvm.tokenize("let if else while print true false and or not")
        for t in toks:
            assert t.kind == "KEYWORD"

    def test_lexer_ident(self) -> None:
        toks = microvm.tokenize("foo Bar _baz")
        assert len(toks) == 3
        assert all(t.kind == "IDENT" for t in toks)

    def test_lexer_longest_op_match(self) -> None:
        toks = microvm.tokenize("== != <= >=")
        assert len(toks) == 4
        for t in toks:
            assert t.kind == "OP"

    def test_lexer_comment(self) -> None:
        toks = microvm.tokenize("let x = 1; // comment\nprint x;")
        assert len(toks) == 8  # let, x, =, 1, ;, print, x, ;

    def test_lexer_unexpected_char(self) -> None:
        with pytest.raises(microvm.errors.LexError):
            microvm.tokenize("let @ = 1;")

    def test_lexer_case_sensitive(self) -> None:
        toks = microvm.tokenize("IF Let")
        assert toks[0].kind == "IDENT"
        assert toks[1].kind == "IDENT"


# ---- Parser tests ----

class TestParser:
    def test_parse_chained_comparison_error(self) -> None:
        with pytest.raises(microvm.errors.ParseError):
            microvm.parse("let x = 1 < 2 < 3;")

    def test_parse_missing_semicolon(self) -> None:
        with pytest.raises(microvm.errors.ParseError):
            microvm.parse("let x = 1")


# ---- Compilation tests ----

class TestCompiler:
    def test_compile_print_literal_three_instrs(self) -> None:
        p = microvm.compile_source("print 1;")
        assert len(p.instructions) == 3
        assert p.instructions[0].op == "CONST"
        assert p.instructions[1].op == "PRINT"
        assert p.instructions[2].op == "HALT"

    def test_compile_duplicate_decl_error(self) -> None:
        with pytest.raises(microvm.errors.CompileError):
            microvm.compile_source("let x = 1; let x = 2;")

    def test_compile_undeclared_read_error(self) -> None:
        with pytest.raises(microvm.errors.CompileError):
            microvm.compile_source("print x;")

    def test_compile_undeclared_assign_error(self) -> None:
        with pytest.raises(microvm.errors.CompileError):
            microvm.compile_source("x = 1;")

    def test_constant_pool_dedup(self) -> None:
        p = microvm.compile_source("let a = 1; let b = 1;")
        assert len(p.constants) == 1  # single int 1

    def test_constant_pool_type_distinct(self) -> None:
        p = microvm.compile_source("let a = 1; let b = 1.0; let c = true;")
        assert len(p.constants) == 3  # 1, 1.0, true are distinct

    def test_if_else_compiles(self) -> None:
        p = microvm.compile_source(
            "if (true) { print 1; } else { print 2; }"
        )
        # Must have HALT as last instruction
        assert p.instructions[-1].op == "HALT"

    def test_while_compiles(self) -> None:
        p = microvm.compile_source(
            "let x = 0; while (x < 3) { x = x + 1; }"
        )
        assert p.instructions[-1].op == "HALT"


# ---- VM execution tests ----

class TestVM:
    def test_add_int(self) -> None:
        p = microvm.compile_source("print 1 + 2;")
        assert microvm.execute(p) == ["3"]

    def test_add_float(self) -> None:
        p = microvm.compile_source("print 1.5 + 2.5;")
        assert microvm.execute(p) == ["4.0"]

    def test_add_string_concat(self) -> None:
        p = microvm.compile_source('print "a" + "b";')
        assert microvm.execute(p) == ["ab"]

    def test_add_string_int_error(self) -> None:
        p = microvm.compile_source('print "a" + 1;')
        with pytest.raises(microvm.errors.VMRuntimeError):
            microvm.execute(p)

    def test_sub_int(self) -> None:
        p = microvm.compile_source("print 5 - 3;")
        assert microvm.execute(p) == ["2"]

    def test_mul_int(self) -> None:
        p = microvm.compile_source("print 3 * 4;")
        assert microvm.execute(p) == ["12"]

    def test_div_yields_float(self) -> None:
        p = microvm.compile_source("print 7 / 2;")
        assert microvm.execute(p) == ["3.5"]

    def test_div_by_zero(self) -> None:
        p = microvm.compile_source("print 1 / 0;")
        with pytest.raises(microvm.errors.VMRuntimeError):
            microvm.execute(p)

    def test_mod_int(self) -> None:
        p = microvm.compile_source("print 7 % 3;")
        assert microvm.execute(p) == ["1"]

    def test_mod_negative(self) -> None:
        p = microvm.compile_source("print -7 % 3;")
        assert microvm.execute(p) == ["2"]

    def test_mod_by_zero(self) -> None:
        p = microvm.compile_source("print 5 % 0;")
        with pytest.raises(microvm.errors.VMRuntimeError):
            microvm.execute(p)

    def test_mod_non_int_error(self) -> None:
        p = microvm.compile_source("print 5 % 2.0;")
        with pytest.raises(microvm.errors.VMRuntimeError):
            microvm.execute(p)

    def test_unary_neg(self) -> None:
        p = microvm.compile_source("print -5;")
        assert microvm.execute(p) == ["-5"]

    def test_unary_neg_float(self) -> None:
        p = microvm.compile_source("print -3.5;")
        assert microvm.execute(p) == ["-3.5"]

    def test_eq_same_type(self) -> None:
        p = microvm.compile_source("print 1 == 1;")
        assert microvm.execute(p) == ["true"]

    def test_eq_cross_type_numeric(self) -> None:
        p = microvm.compile_source("print 1 == 1.0;")
        assert microvm.execute(p) == ["true"]

    def test_eq_bool_vs_int(self) -> None:
        p = microvm.compile_source("print true == 1;")
        assert microvm.execute(p) == ["false"]

    def test_lt_numbers(self) -> None:
        p = microvm.compile_source("print 2 < 3;")
        assert microvm.execute(p) == ["true"]

    def test_lt_strings(self) -> None:
        p = microvm.compile_source('print "a" < "b";')
        assert microvm.execute(p) == ["true"]

    def test_lt_bool_error(self) -> None:
        p = microvm.compile_source("print true < false;")
        with pytest.raises(microvm.errors.VMRuntimeError):
            microvm.execute(p)

    def test_not_bool(self) -> None:
        p = microvm.compile_source("print not true;")
        assert microvm.execute(p) == ["false"]

    def test_not_non_bool_error(self) -> None:
        p = microvm.compile_source("print not 5;")
        with pytest.raises(microvm.errors.VMRuntimeError):
            microvm.execute(p)

    def test_and_short_circuit_false(self) -> None:
        p = microvm.compile_source(
            "let x = false and (1 / 0 == 0); print x;"
        )
        assert microvm.execute(p) == ["false"]

    def test_and_right_checked_true(self) -> None:
        p = microvm.compile_source("let x = true and 5;")
        with pytest.raises(microvm.errors.VMRuntimeError):
            microvm.execute(p)

    def test_or_short_circuit_true(self) -> None:
        p = microvm.compile_source(
            "let x = true or (1 / 0 == 0); print x;"
        )
        assert microvm.execute(p) == ["true"]

    def test_or_right_checked_false(self) -> None:
        p = microvm.compile_source("let x = false or 5;")
        with pytest.raises(microvm.errors.VMRuntimeError):
            microvm.execute(p)

    def test_if_condition_must_be_bool(self) -> None:
        p = microvm.compile_source("if (5) { print 1; }")
        with pytest.raises(microvm.errors.VMRuntimeError):
            microvm.execute(p)

    def test_while_condition_must_be_bool(self) -> None:
        p = microvm.compile_source("let x = 1; while (x) { x = 0; }")
        with pytest.raises(microvm.errors.VMRuntimeError):
            microvm.execute(p)

    def test_never_assigned_variable(self) -> None:
            # y is declared inside an if that never executes, so y is never assigned
            p = microvm.compile_source(
                "if (false) { let y = true; } print y;"
            )
            with pytest.raises(microvm.errors.VMRuntimeError):
                microvm.execute(p)

    def test_while_loop(self) -> None:
        p = microvm.compile_source(
            "let x = 3; while (x > 0) { print x; x = x - 1; }"
        )
        assert microvm.execute(p) == ["3", "2", "1"]

    def test_if_else_if_else(self) -> None:
        src = """
let x = 3;
if (x > 5) { print "big"; }
else if (x > 2) { print "mid"; }
else { print "small"; }
"""
        p = microvm.compile_source(src)
        assert microvm.execute(p) == ["mid"]

    def test_print_bool(self) -> None:
        p = microvm.compile_source("print true; print false;")
        assert microvm.execute(p) == ["true", "false"]

    def test_print_float(self) -> None:
        p = microvm.compile_source("print 4 / 2;")
        assert microvm.execute(p) == ["2.0"]

    def test_step_limit(self) -> None:
        p = microvm.compile_source("while (true) {}")
        with pytest.raises(microvm.errors.StepLimitError):
            microvm.execute(p, step_limit=50)

    def test_step_limit_positive_int_check(self) -> None:
        p = microvm.compile_source("print 1;")
        with pytest.raises(ValueError):
            microvm.execute(p, step_limit=0)
        with pytest.raises(ValueError):
            microvm.execute(p, step_limit=True)


# ---- Optimizer tests ----

class TestOptimizer:
    def test_optimize_folds_arithmetic(self) -> None:
        p = microvm.compile_source("print 1 + 2 * 3;", optimize=True)
        assert len(p.instructions) == 3  # CONST, PRINT, HALT

    def test_optimize_no_fold_div_by_zero(self) -> None:
        p = microvm.compile_source("print 1 / 0;", optimize=True)
        with pytest.raises(microvm.errors.VMRuntimeError):
            microvm.execute(p)

    def test_optimize_no_fold_true_and_nonbool(self) -> None:
        p = microvm.compile_source("let x = true and 5;", optimize=True)
        with pytest.raises(microvm.errors.VMRuntimeError):
            microvm.execute(p)

    def test_optimize_folds_false_and_anything(self) -> None:
        p = microvm.compile_source("let x = false and (1 / 0);", optimize=True)
        # Folds to false; 1/0 never evaluated
        # x is assigned false, no error
        microvm.execute(p)  # must not raise

    def test_optimize_folds_true_or_anything(self) -> None:
        p = microvm.compile_source("let x = true or (1 / 0);", optimize=True)
        microvm.execute(p)  # must not raise

    def test_optimize_folds_comparison(self) -> None:
        p = microvm.compile_source("print 1 < 2;", optimize=True)
        assert microvm.execute(p) == ["true"]

    def test_optimize_folds_not(self) -> None:
        p = microvm.compile_source("print not false;", optimize=True)
        assert microvm.execute(p) == ["true"]


# ---- Serializer tests ----

class TestSerializer:
    def test_round_trip(self) -> None:
        p = microvm.compile_source("let x = 5; let y = true; print x + y;")
        data = microvm.dumps(p)
        p2 = microvm.loads(data)
        assert p.constants == p2.constants
        assert p.names == p2.names
        assert len(p.instructions) == len(p2.instructions)

    def test_round_trip_execution(self) -> None:
        p = microvm.compile_source("let x = 5; print x; print 8 / 2;")
        out1 = microvm.execute(p)
        data = microvm.dumps(p)
        p2 = microvm.loads(data)
        out2 = microvm.execute(p2)
        assert out1 == out2

    def test_deterministic(self) -> None:
        p = microvm.compile_source("print 1 + 2;")
        data1 = microvm.dumps(p)
        data2 = microvm.dumps(p)
        assert data1 == data2

    def test_bad_magic(self) -> None:
        with pytest.raises(microvm.errors.SerializationError):
            microvm.loads(b"\x00" * 20)

    def test_bad_version(self) -> None:
        data = b"MVM1\x02"
        data += b"\x00" * 100
        with pytest.raises(microvm.errors.SerializationError):
            microvm.loads(data)

    def test_checksum_mismatch(self) -> None:
        data = bytearray(microvm.dumps(microvm.compile_source("print 1;")))
        data[-1] ^= 0xFF
        with pytest.raises(microvm.errors.SerializationError):
            microvm.loads(bytes(data))

    def test_trailing_bytes(self) -> None:
        data = microvm.dumps(microvm.compile_source("print 1;"))
        with pytest.raises(microvm.errors.SerializationError):
            microvm.loads(data + b"extra")

    def test_truncated_data(self) -> None:
        data = microvm.dumps(microvm.compile_source("print 1;"))
        with pytest.raises(microvm.errors.SerializationError):
            microvm.loads(data[:10])

    def test_int_out_of_i64_range(self) -> None:
        big = 2**63
        p = microvm.compile_source(f"let x = {big};")
        with pytest.raises(microvm.errors.SerializationError):
            microvm.dumps(p)

    def test_bool_constant_encoding(self) -> None:
        p = microvm.compile_source("let x = true; let y = false;")
        data = microvm.dumps(p)
        p2 = microvm.loads(data)
        assert p2.constants == [True, False]


# ---- Disassembler tests ----

class TestDisassembler:
    def test_disasm_print_literal(self) -> None:
        p = microvm.compile_source("print 1;")
        expected = "0000 CONST 0  ; 1\n0001 PRINT\n0002 HALT\n"
        assert microvm.disassemble(p) == expected

    def test_disasm_const_string(self) -> None:
        p = microvm.compile_source('print "hello\nworld";')
        d = microvm.disassemble(p)
        assert "; \"hello\\nworld\"" in d


# ---- CLI tests ----

class TestCLI:
    def test_cli_run(self, tmp_path) -> None:
        f = tmp_path / "test.mv"
        f.write_text("print 42;")
        r = subprocess.run(
            [sys.executable, "-m", "microvm", "run", str(f)],
            capture_output=True, text=True
        )
        assert r.returncode == 0
        assert r.stdout.strip() == "42"

    def test_cli_run_optimize(self, tmp_path) -> None:
        f = tmp_path / "test.mv"
        f.write_text("print 1 + 2 * 3;")
        r = subprocess.run(
            [sys.executable, "-m", "microvm", "run", "--optimize", str(f)],
            capture_output=True, text=True
        )
        assert r.returncode == 0
        assert r.stdout.strip() == "7"

    def test_cli_run_step_limit(self, tmp_path) -> None:
        f = tmp_path / "loop.mv"
        f.write_text("while (true) {}")
        r = subprocess.run(
            [sys.executable, "-m", "microvm", "run", "--step-limit", "50", str(f)],
            capture_output=True, text=True
        )
        assert r.returncode == 3
        assert "Error:" in r.stderr

    def test_cli_build_and_exec(self, tmp_path) -> None:
        src = tmp_path / "test.mv"
        src.write_text("print 99;")
        out = tmp_path / "test.mvb"
        r1 = subprocess.run(
            [sys.executable, "-m", "microvm", "build", str(src), str(out)],
            capture_output=True, text=True
        )
        assert r1.returncode == 0
        assert out.exists()
        r2 = subprocess.run(
            [sys.executable, "-m", "microvm", "exec", str(out)],
            capture_output=True, text=True
        )
        assert r2.returncode == 0
        assert r2.stdout.strip() == "99"

    def test_cli_disasm(self, tmp_path) -> None:
        src = tmp_path / "test.mv"
        src.write_text("print 1;")
        out = tmp_path / "test.mvb"
        subprocess.run(
            [sys.executable, "-m", "microvm", "build", str(src), str(out)],
            capture_output=True
        )
        r = subprocess.run(
            [sys.executable, "-m", "microvm", "disasm", str(out)],
            capture_output=True, text=True
        )
        assert r.returncode == 0
        assert "CONST" in r.stdout

    def test_cli_nonexistent_file(self) -> None:
        r = subprocess.run(
            [sys.executable, "-m", "microvm", "run", "nonexistent.mv"],
            capture_output=True, text=True
        )
        assert r.returncode == 2

    def test_cli_compile_error_exit_code(self, tmp_path) -> None:
        f = tmp_path / "bad.mv"
        f.write_text("let x = ;")
        r = subprocess.run(
            [sys.executable, "-m", "microvm", "run", str(f)],
            capture_output=True, text=True
        )
        assert r.returncode == 3


# ---- Acceptance criterion ----

class TestAcceptance:
    def test_acceptance_criterion_3(self) -> None:
        """Prints 5 then 4.0"""
        p = microvm.compile_source("let x = 5; print x; print 8 / 2;")
        out = microvm.execute(p)
        assert out == ["5", "4.0"]

    def test_acceptance_import_len(self) -> None:
        assert len(microvm.__all__) == 19