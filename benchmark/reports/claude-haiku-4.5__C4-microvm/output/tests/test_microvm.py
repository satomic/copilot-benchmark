import pytest
import tempfile
import os
from microvm import (
    tokenize, Token, parse, compile_source, Program, Instr,
    fold_constants, execute, dumps, loads, disassemble, OPCODES, OPCODE_NUMBERS,
    MicroVMError, LexError, ParseError, CompileError, SerializationError, VMRuntimeError
)


class TestLexer:
    def test_int_token(self):
        tokens = tokenize("42")
        assert len(tokens) == 1
        assert tokens[0].kind == "INT"
        assert tokens[0].value == 42

    def test_float_with_exponent(self):
        tokens = tokenize("1.5e3")
        assert tokens[0].kind == "FLOAT"
        assert tokens[0].value == 1500.0

    def test_invalid_float_no_digits_after_dot(self):
        with pytest.raises(LexError) as exc:
            tokenize("1.")
        assert exc.value.offset == 0

    def test_invalid_float_dot_only(self):
        with pytest.raises(LexError):
            tokenize(".5")

    def test_string_with_escapes(self):
        tokens = tokenize(r'"hello\nworld"')
        assert tokens[0].kind == "STRING"
        assert tokens[0].value == "hello\nworld"

    def test_string_escape_quote(self):
        tokens = tokenize(r'"say \"hi\""')
        assert tokens[0].value == 'say "hi"'

    def test_string_escape_backslash(self):
        tokens = tokenize(r'"a\\b"')
        assert tokens[0].value == "a\\b"

    def test_invalid_string_escape(self):
        with pytest.raises(LexError):
            tokenize(r'"bad\x"')

    def test_unterminated_string(self):
        with pytest.raises(LexError):
            tokenize('"unclosed')

    def test_literal_newline_in_string(self):
        with pytest.raises(LexError):
            tokenize('"line1\nline2"')

    def test_keyword_let(self):
        tokens = tokenize("let")
        assert tokens[0].kind == "KEYWORD"
        assert tokens[0].value == "let"

    def test_identifier_let_uppercase(self):
        tokens = tokenize("Let")
        assert tokens[0].kind == "IDENT"

    def test_comment_ignored(self):
        tokens = tokenize("42 // comment\n43")
        assert len(tokens) == 2
        assert tokens[0].value == 42
        assert tokens[1].value == 43

    def test_operator_longest_match(self):
        tokens = tokenize("==")
        assert len(tokens) == 1
        assert tokens[0].value == "=="

    def test_token_offset(self):
        tokens = tokenize("  x")
        assert tokens[0].offset == 2


class TestParser:
    def test_parse_let(self):
        ast = parse("let x = 1;")
        assert len(ast.statements) == 1

    def test_parse_comparison_not_associative(self):
        with pytest.raises(ParseError):
            parse("1 < 2 < 3")

    def test_parse_if_else(self):
        ast = parse("if (true) { print 1; } else { print 2; }")
        assert len(ast.statements) == 1

    def test_parse_while(self):
        ast = parse("while (true) { print 1; }")
        assert len(ast.statements) == 1


class TestCompiler:
    def test_compile_print_literal_instructions(self):
        prog = compile_source("print 1;")
        assert len(prog.instructions) == 3
        assert prog.instructions[0].op == "CONST"
        assert prog.instructions[1].op == "PRINT"
        assert prog.instructions[2].op == "HALT"

    def test_const_pool_dedup_int(self):
        prog = compile_source("let x = 1; let y = 1; print x;")
        assert prog.constants.count(1) == 1

    def test_const_pool_int_vs_float(self):
        prog = compile_source("let x = 1; let y = 1.0; print x; print y;")
        assert 1 in prog.constants
        assert 1.0 in prog.constants

    def test_const_pool_bool_vs_int(self):
        prog = compile_source("let x = true; let y = 1; print x; print y;")
        assert True in prog.constants
        assert 1 in prog.constants

    def test_declare_twice_error(self):
        with pytest.raises(CompileError):
            compile_source("let x = 1; let x = 2;")

    def test_use_undeclared_error(self):
        with pytest.raises(CompileError):
            compile_source("print x;")

    def test_assign_undeclared_error(self):
        with pytest.raises(CompileError):
            compile_source("x = 1;")


class TestVM:
    def test_execute_print_int(self):
        prog = compile_source("print 42;")
        output = execute(prog)
        assert output == ["42"]

    def test_execute_print_float(self):
        prog = compile_source("print 3.5;")
        output = execute(prog)
        assert output == ["3.5"]

    def test_execute_print_bool(self):
        prog = compile_source("print true;")
        output = execute(prog)
        assert output == ["true"]

    def test_execute_print_string(self):
        prog = compile_source('print "hello";')
        output = execute(prog)
        assert output == ["hello"]

    def test_add_int_int(self):
        prog = compile_source("print 2 + 3;")
        output = execute(prog)
        assert output == ["5"]

    def test_add_float_int(self):
        prog = compile_source("print 2.5 + 1;")
        output = execute(prog)
        assert output == ["3.5"]

    def test_add_string_string(self):
        prog = compile_source('print "a" + "b";')
        output = execute(prog)
        assert output == ["ab"]

    def test_add_string_int_error(self):
        prog = compile_source('print "a" + 1;')
        with pytest.raises(VMRuntimeError):
            execute(prog)

    def test_div_always_float(self):
        prog = compile_source("print 7 / 2;")
        output = execute(prog)
        assert output == ["3.5"]

    def test_div_by_zero_error(self):
        prog = compile_source("print 1 / 0;")
        with pytest.raises(VMRuntimeError):
            execute(prog)

    def test_mod_int_int(self):
        prog = compile_source("print 7 % 3;")
        output = execute(prog)
        assert output == ["1"]

    def test_mod_by_zero_error(self):
        prog = compile_source("print 1 % 0;")
        with pytest.raises(VMRuntimeError):
            execute(prog)

    def test_eq_different_types(self):
        prog = compile_source("print 1 == 1.0;")
        output = execute(prog)
        assert output == ["true"]

    def test_eq_bool_vs_int(self):
        prog = compile_source("print true == 1;")
        output = execute(prog)
        assert output == ["false"]

    def test_lt_requires_numbers_or_strings(self):
        prog = compile_source("print true < 1;")
        with pytest.raises(VMRuntimeError):
            execute(prog)

    def test_and_short_circuit(self):
        prog = compile_source("print false and (1 / 0 == 0);")
        output = execute(prog)
        assert output == ["false"]

    def test_or_short_circuit(self):
        prog = compile_source("print true or (1 / 0 == 0);")
        output = execute(prog)
        assert output == ["true"]

    def test_and_non_bool_error(self):
        prog = compile_source("print true and 5;")
        with pytest.raises(VMRuntimeError):
            execute(prog)

    def test_unassigned_variable_error(self):
        prog = compile_source("let x = 1; if (false) { let y = 2; } print y;")
        with pytest.raises(VMRuntimeError) as exc:
            execute(prog)
        assert "y" in str(exc.value)

    def test_step_limit_exceeded(self):
        prog = compile_source("while (true) { }")
        with pytest.raises(VMRuntimeError):
            execute(prog, step_limit=10)

    def test_step_limit_must_be_positive_int(self):
        prog = compile_source("print 1;")
        with pytest.raises(ValueError):
            execute(prog, step_limit=0)
        with pytest.raises(ValueError):
            execute(prog, step_limit=-1)
        with pytest.raises(ValueError):
            execute(prog, step_limit=True)

    def test_negate_number(self):
        prog = compile_source("print -5;")
        output = execute(prog)
        assert output == ["-5"]

    def test_negate_bool_error(self):
        prog = compile_source("print -true;")
        with pytest.raises(VMRuntimeError):
            execute(prog)

    def test_not_bool(self):
        prog = compile_source("print not true;")
        output = execute(prog)
        assert output == ["false"]

    def test_not_int_error(self):
        prog = compile_source("print not 5;")
        with pytest.raises(VMRuntimeError):
            execute(prog)


class TestOptimizer:
    def test_fold_arithmetic(self):
        prog = compile_source("print 1 + 2 * 3;", optimize=True)
        assert len(prog.instructions) == 3

    def test_fold_div_by_zero_not_folded(self):
        prog = compile_source("print 1 / 0;", optimize=True)
        with pytest.raises(VMRuntimeError):
            execute(prog)

    def test_fold_and_with_false_short_circuit(self):
        prog = compile_source("print false and (1 / 0 == 0);", optimize=True)
        output = execute(prog)
        assert output == ["false"]

    def test_fold_true_and_x_not_folded(self):
        prog = compile_source("print true and 5;", optimize=True)
        with pytest.raises(VMRuntimeError):
            execute(prog)


class TestSerializer:
    def test_dumps_loads_roundtrip(self):
        prog = compile_source("print 42;")
        data = dumps(prog)
        prog2 = loads(data)
        output1 = execute(prog)
        output2 = execute(prog2)
        assert output1 == output2

    def test_magic_validation(self):
        with pytest.raises(SerializationError):
            loads(b"XXXX")

    def test_checksum_mismatch(self):
        prog = compile_source("print 1;")
        data = bytearray(dumps(prog))
        data[-1] ^= 1
        with pytest.raises(SerializationError):
            loads(bytes(data))

    def test_truncated_file(self):
        with pytest.raises(SerializationError):
            loads(b"MVM")

    def test_trailing_bytes(self):
        prog = compile_source("print 1;")
        data = dumps(prog) + b"extra"
        with pytest.raises(SerializationError):
            loads(data)

    def test_int_out_of_range(self):
        prog = Program([2**63], ["x"], [Instr("CONST", 0), Instr("HALT", None)])
        with pytest.raises(SerializationError):
            dumps(prog)


class TestDisassembler:
    def test_disassemble_print_literal(self):
        prog = compile_source("print 1;")
        output = disassemble(prog)
        assert "0000 CONST 0  ; 1\n" in output
        assert "0001 PRINT\n" in output
        assert "0002 HALT\n" in output

    def test_disassemble_bool_const(self):
        prog = compile_source("print true;")
        output = disassemble(prog)
        assert "; true" in output

    def test_disassemble_string_const(self):
        prog = compile_source('print "a\\nb";')
        output = disassemble(prog)
        assert '"; \\"a\\\\nb\\"' in output or '; "a\\nb"' in output


class TestIntegration:
    def test_division_result_float(self):
        prog = compile_source("print 8 / 2;")
        output = execute(prog)
        assert output == ["4.0"]

    def test_modulo_sign_rule(self):
        prog = compile_source("print -7 % 3;")
        output = execute(prog)
        assert output == ["2"]

    def test_if_else_if_chain(self):
        prog = compile_source("""
            let x = 3;
            if (x > 5) { print "big"; } else if (x > 2) { print "mid"; } else { print "small"; }
        """)
        output = execute(prog)
        assert output == ["mid"]

    def test_while_loop(self):
        prog = compile_source("""
            let x = 3;
            while (x > 0) { print x; x = x - 1; }
        """)
        output = execute(prog)
        assert output == ["3", "2", "1"]

    def test_block_no_scope(self):
        with pytest.raises(CompileError):
            compile_source("""
                let x = 1;
                { let x = 2; print x; }
                print x;
            """)

    def test_comparison_types(self):
        prog = compile_source("print 1 < 2;")
        output = execute(prog)
        assert output == ["true"]

    def test_string_comparison(self):
        prog = compile_source('print "a" < "b";')
        output = execute(prog)
        assert output == ["true"]

    def test_and_operator_precedence(self):
        prog = compile_source("print true or false and false;")
        output = execute(prog)
        assert output == ["true"]


class TestCLI:
    def test_run_command(self, tmp_path):
        prog_file = tmp_path / "prog.mv"
        prog_file.write_text("print 5;")
        from microvm.__main__ import main
        ret = main(["run", str(prog_file)])
        assert ret == 0

    def test_build_command(self, tmp_path):
        prog_file = tmp_path / "prog.mv"
        out_file = tmp_path / "prog.mvm"
        prog_file.write_text("print 42;")
        from microvm.__main__ import main
        ret = main(["build", str(prog_file), str(out_file)])
        assert ret == 0
        assert out_file.exists()

    def test_exec_command(self, tmp_path):
        prog_file = tmp_path / "prog.mv"
        out_file = tmp_path / "prog.mvm"
        prog_file.write_text("print 7;")
        from microvm.__main__ import main
        ret = main(["build", str(prog_file), str(out_file)])
        assert ret == 0
        ret = main(["exec", str(out_file)])
        assert ret == 0

    def test_disasm_command(self, tmp_path):
        prog_file = tmp_path / "prog.mv"
        out_file = tmp_path / "prog.mvm"
        prog_file.write_text("print 1;")
        from microvm.__main__ import main
        ret = main(["build", str(prog_file), str(out_file)])
        assert ret == 0
        ret = main(["disasm", str(out_file)])
        assert ret == 0

    def test_cli_exit_code_on_error(self, tmp_path):
        prog_file = tmp_path / "prog.mv"
        prog_file.write_text("print undefined;")
        from microvm.__main__ import main
        ret = main(["run", str(prog_file)])
        assert ret == 3

    def test_cli_missing_file(self):
        from microvm.__main__ import main
        ret = main(["run", "/nonexistent/file.mv"])
        assert ret == 2
