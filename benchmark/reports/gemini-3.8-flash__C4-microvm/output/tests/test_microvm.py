"""Comprehensive test suite for microvm."""

import pathlib
import pytest
from microvm import (
    CompileError,
    Instr,
    LexError,
    MicroVMError,
    OPCODE_NUMBERS,
    OPCODES,
    ParseError,
    Program,
    SerializationError,
    Token,
    VMRuntimeError,
    compile_source,
    disassemble,
    dumps,
    execute,
    fold_constants,
    loads,
    parse,
    tokenize,
)
from microvm.__main__ import main
from microvm.errors import StepLimitError


def run_code(src: str, *, optimize: bool = False, step_limit: int = 100_000) -> list[str]:
    prog = compile_source(src, optimize=optimize)
    return execute(prog, step_limit=step_limit)


# 1. Semantic rule 1: + - * numbers, INT op INT -> INT, FLOAT op -> FLOAT
def test_arithmetic_types() -> None:
    assert run_code("print 2 + 3;") == ["5"]
    assert run_code("print 5 - 2;") == ["3"]
    assert run_code("print 4 * 3;") == ["12"]
    assert run_code("print 2.5 + 3;") == ["5.5"]
    assert run_code("print 5.0 - 2;") == ["3.0"]
    assert run_code("print 4 * 2.5;") == ["10.0"]


# 2. Semantic rule 1 exception: + on strings
def test_string_concat() -> None:
    assert run_code('print "hello" + " " + "world";') == ["hello world"]


# 3. Semantic rule 1 errors: string + int, string * int
def test_string_arithmetic_errors() -> None:
    with pytest.raises(VMRuntimeError):
        run_code('print "a" + 1;')
    with pytest.raises(VMRuntimeError):
        run_code('print "a" * 2;')


# 4. Semantic rule 1 errors: bool is not a number
def test_bool_arithmetic_errors() -> None:
    with pytest.raises(VMRuntimeError):
        run_code("print true + 1;")
    with pytest.raises(VMRuntimeError):
        run_code("print false * 5;")
    with pytest.raises(VMRuntimeError):
        run_code("print true + false;")


# 5. Semantic rule 2: / always yields FLOAT
def test_division_yields_float() -> None:
    assert run_code("print 7 / 2;") == ["3.5"]
    assert run_code("print 4 / 2;") == ["2.0"]
    assert run_code("print 9.0 / 3.0;") == ["3.0"]


# 6. Semantic rule 2: % requires two INTs and follows Python's sign rule
def test_modulo() -> None:
    assert run_code("print 7 % 3;") == ["1"]
    assert run_code("print -7 % 3;") == ["2"]
    assert run_code("print 7 % -3;") == ["-2"]


# 7. Semantic rule 2 error: % with float or bool
def test_modulo_errors() -> None:
    with pytest.raises(VMRuntimeError):
        run_code("print 7.0 % 3;")
    with pytest.raises(VMRuntimeError):
        run_code("print 7 % true;")


# 8. Semantic rule 3: Division or modulo by zero
def test_division_modulo_by_zero() -> None:
    with pytest.raises(VMRuntimeError):
        run_code("print 5 / 0;")
    with pytest.raises(VMRuntimeError):
        run_code("print 5.0 / 0.0;")
    with pytest.raises(VMRuntimeError):
        run_code("print 5 % 0;")


# 9. Semantic rule 4: Unary - requires number
def test_unary_neg() -> None:
    assert run_code("print -5;") == ["-5"]
    assert run_code("print -3.14;") == ["-3.14"]
    assert run_code("print - - 7;") == ["7"]
    with pytest.raises(VMRuntimeError):
        run_code("print -true;")
    with pytest.raises(VMRuntimeError):
        run_code('print -"hello";')


# 10. Semantic rule 5: == and != never raise
def test_equality_and_inequality() -> None:
    assert run_code("print true == 1;") == ["false"]
    assert run_code("print true != 1;") == ["true"]
    assert run_code("print 1 == 1.0;") == ["true"]
    assert run_code("print 1 != 1.0;") == ["false"]
    assert run_code('print "abc" == "abc";') == ["true"]
    assert run_code('print "abc" == 123;') == ["false"]
    assert run_code('print "abc" != 123;') == ["true"]


# 11. Semantic rule 6: comparisons < <= > >= on numbers
def test_number_comparisons() -> None:
    assert run_code("print 1 < 2;") == ["true"]
    assert run_code("print 2.0 <= 2;") == ["true"]
    assert run_code("print 3 > 3.5;") == ["false"]
    assert run_code("print 4 >= 4.0;") == ["true"]


# 12. Semantic rule 6: comparisons on strings
def test_string_comparisons() -> None:
    assert run_code('print "apple" < "banana";') == ["true"]
    assert run_code('print "cat" >= "dog";') == ["false"]


# 13. Semantic rule 6 errors: comparisons with bool or mixed types
def test_comparison_type_errors() -> None:
    with pytest.raises(VMRuntimeError):
        run_code("print true < false;")
    with pytest.raises(VMRuntimeError):
        run_code('print 1 < "2";')
    with pytest.raises(VMRuntimeError):
        run_code("print true <= 1;")


# 14. Semantic rule 7: short-circuit and without evaluating right
def test_short_circuit_and() -> None:
    assert run_code("print false and (1 / 0 == 0);") == ["false"]


# 15. Semantic rule 7: short-circuit or without evaluating right
def test_short_circuit_or() -> None:
    assert run_code("print true or (1 / 0 == 0);") == ["true"]


# 16. Semantic rule 7: strict-bool on evaluated operand
def test_strict_bool_and_or() -> None:
    with pytest.raises(VMRuntimeError):
        run_code("print true and 5;")
    with pytest.raises(VMRuntimeError):
        run_code("print false or 5;")
    with pytest.raises(VMRuntimeError):
        run_code("print 5 and true;")
    with pytest.raises(VMRuntimeError):
        run_code("print 5 or false;")


# 17. Semantic rule 7: not
def test_not_operator() -> None:
    assert run_code("print not true;") == ["false"]
    assert run_code("print not false;") == ["true"]
    assert run_code("print not not true;") == ["true"]
    with pytest.raises(VMRuntimeError):
        run_code("print not 0;")


# 18. Semantic rule 8: condition of if must be BOOL
def test_if_condition_type() -> None:
    with pytest.raises(VMRuntimeError):
        run_code("if (1) { print 1; }")
    with pytest.raises(VMRuntimeError):
        run_code('if ("true") { print 1; }')


# 19. Semantic rule 8: condition of while must be BOOL
def test_while_condition_type() -> None:
    with pytest.raises(VMRuntimeError):
        run_code("while (0) { print 1; }")


# 20. Semantic rule 9: print rendering
def test_print_rendering() -> None:
    src = """
    print 42;
    print 4 / 2;
    print true;
    print false;
    print "raw text";
    """
    assert run_code(src) == ["42", "2.0", "true", "false", "raw text"]


# 21. Declared but never assigned variable raises VMRuntimeError naming the variable
def test_unassigned_variable_error() -> None:
    src = """
    if (false) {
        let x = 10;
    }
    print x;
    """
    with pytest.raises(VMRuntimeError) as exc_info:
        run_code(src)
    assert "'x'" in str(exc_info.value) or "x" in str(exc_info.value)


# 22. Assigning to never-declared variable is CompileError
def test_assign_undeclared_compile_error() -> None:
    with pytest.raises(CompileError):
        run_code("x = 5;")


# 23. Reading never-declared variable is CompileError
def test_read_undeclared_compile_error() -> None:
    with pytest.raises(CompileError):
        run_code("print x;")


# 24. Duplicate let declaration is CompileError
def test_duplicate_let_compile_error() -> None:
    with pytest.raises(CompileError):
        run_code("let x = 1; let x = 2;")
    with pytest.raises(CompileError):
        run_code("let x = 1; { let x = 2; }")


# 25. Global namespace: let in block accessible outside
def test_block_scope_global() -> None:
    src = """
    {
        let a = 100;
    }
    print a;
    """
    assert run_code(src) == ["100"]


# 26. Constant pool deduplication by type and value
def test_constant_pool_dedup() -> None:
    src = """
    let a = 1;
    let b = 1;
    let c = 1.0;
    let d = true;
    """
    prog = compile_source(src)
    assert 1 in prog.constants
    assert 1.0 in prog.constants
    assert True in prog.constants
    keys = [(type(c), c) for c in prog.constants]
    assert len(keys) == len(set(keys))
    assert (int, 1) in keys
    assert (float, 1.0) in keys
    assert (bool, True) in keys


# 27. Constant folding: 1 + 2 * 3 compiles to 3 instructions
def test_fold_arithmetic_instructions() -> None:
    prog_unopt = compile_source("print 1 + 2 * 3;", optimize=False)
    prog_opt = compile_source("print 1 + 2 * 3;", optimize=True)
    assert len(prog_unopt.instructions) > 3
    assert len(prog_opt.instructions) == 3
    assert [i.op for i in prog_opt.instructions] == ["CONST", "PRINT", "HALT"]
    assert execute(prog_opt) == ["7"]


# 28. Fold safety: 1 / 0 stays unfolded
def test_fold_safety_div_zero() -> None:
    prog_opt = compile_source("print 1 / 0;", optimize=True)
    with pytest.raises(VMRuntimeError):
        execute(prog_opt)


# 29. Fold safety: true and 5 stays unfolded
def test_fold_safety_true_and_5() -> None:
    prog_opt = compile_source("let y = true and 5;", optimize=True)
    with pytest.raises(VMRuntimeError):
        execute(prog_opt)


# 30. Fold safety: false or 5 stays unfolded
def test_fold_safety_false_or_5() -> None:
    prog_opt = compile_source("let y = false or 5;", optimize=True)
    with pytest.raises(VMRuntimeError):
        execute(prog_opt)


# 31. Fold safety: false and X folds to false
def test_fold_false_and_x() -> None:
    prog_opt = compile_source("print false and (1 / 0 == 0);", optimize=True)
    assert len(prog_opt.instructions) == 3
    assert execute(prog_opt) == ["false"]


# 32. Fold safety: true or X folds to true
def test_fold_true_or_x() -> None:
    prog_opt = compile_source("print true or (1 / 0 == 0);", optimize=True)
    assert len(prog_opt.instructions) == 3
    assert execute(prog_opt) == ["true"]


# 33. Disassembly exact match for section 8
def test_disassemble_exact() -> None:
    prog = compile_source("print 1;")
    dis = disassemble(prog)
    expected = "0000 CONST 0  ; 1\n0001 PRINT\n0002 HALT\n"
    assert dis == expected


# 34. Disassembly format for other types
def test_disassemble_types() -> None:
    src = 'print "hello\\nworld"; print true; print 2.5;'
    prog = compile_source(src)
    dis = disassemble(prog)
    assert 'CONST 0  ; "hello\\nworld"' in dis
    assert "CONST 1  ; true" in dis
    assert "CONST 2  ; 2.5" in dis


# 35. Serializer roundtrip
def test_serializer_roundtrip() -> None:
    src = """
    let x = 10;
    let y = "test";
    if (x > 5) {
        y = y + " passed";
    }
    print y;
    """
    prog = compile_source(src)
    data = dumps(prog)
    loaded = loads(data)
    assert execute(loaded) == execute(prog)


# 36. Serializer corruption: bad magic
def test_serializer_bad_magic() -> None:
    prog = compile_source("print 1;")
    data = bytearray(dumps(prog))
    data[0:4] = b"BADM"
    with pytest.raises(SerializationError):
        loads(bytes(data))


# 37. Serializer corruption: checksum mismatch
def test_serializer_bad_checksum() -> None:
    prog = compile_source("print 1;")
    data = bytearray(dumps(prog))
    data[-1] ^= 0xFF
    with pytest.raises(SerializationError):
        loads(bytes(data))


# 38. Serializer corruption: truncated data
def test_serializer_truncated() -> None:
    prog = compile_source("print 1;")
    data = dumps(prog)
    with pytest.raises(SerializationError):
        loads(data[:10])


# 39. Serializer corruption: invalid bool payload
def test_serializer_invalid_bool() -> None:
    prog = compile_source("print true;")
    data = dumps(prog)
    tag_idx = data.find(b"\x04")
    assert tag_idx != -1
    corrupt = bytearray(data)
    corrupt[tag_idx + 1] = 2  # not 0 or 1
    # recompute crc
    import struct, zlib
    crc = zlib.crc32(corrupt[4:-4]) & 0xFFFFFFFF
    corrupt[-4:] = struct.pack(">I", crc)
    with pytest.raises(SerializationError):
        loads(bytes(corrupt))


# 40. Serializer: int outside 64-bit signed range
def test_serializer_int_overflow() -> None:
    prog = Program(constants=[2**63], names=[], instructions=[Instr("HALT", None)])
    with pytest.raises(SerializationError):
        dumps(prog)


# 41. VM step limit exceeded
def test_step_limit_error() -> None:
    with pytest.raises(StepLimitError):
        run_code("while (true) {}", step_limit=50)


# 42. VM step limit parameter validation
def test_step_limit_validation() -> None:
    prog = compile_source("print 1;")
    with pytest.raises(ValueError):
        execute(prog, step_limit=0)
    with pytest.raises(ValueError):
        execute(prog, step_limit=-10)
    with pytest.raises(ValueError):
        execute(prog, step_limit=True)  # type: ignore[arg-type]


# 43. Lexer error: 1. and .5
def test_lexer_dot_errors() -> None:
    with pytest.raises(LexError) as exc1:
        tokenize("1.")
    assert exc1.value.offset >= 0
    with pytest.raises(LexError) as exc2:
        tokenize(".5")
    assert exc2.value.offset >= 0


# 44. Lexer error: invalid string escape and unterminated string
def test_lexer_string_errors() -> None:
    with pytest.raises(LexError):
        tokenize('"bad escape \\k"')
    with pytest.raises(LexError):
        tokenize('"unterminated')
    with pytest.raises(LexError):
        tokenize('"line\nbreak"')


# 45. Parser error: comparison non-associativity
def test_parser_comparison_non_associative() -> None:
    with pytest.raises(ParseError) as exc:
        parse("print 1 < 2 < 3;")
    assert exc.value.offset >= 0
    with pytest.raises(ParseError):
        parse("print 1 == 2 == 3;")


# 46. Parser error: malformed statements
def test_parser_syntax_errors() -> None:
    with pytest.raises(ParseError):
        parse("let = 1;")
    with pytest.raises(ParseError):
        parse("if x > 5 { print 1; }")


# 47. CLI: run success
def test_cli_run_success(tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]) -> None:
    src_file = tmp_path / "test.mv"
    src_file.write_text("print 42;", encoding="utf-8")
    ret = main(["run", str(src_file)])
    captured = capsys.readouterr()
    assert ret == 0
    assert captured.out.strip() == "42"


# 48. CLI: run runtime error exit code 3 and empty stdout
def test_cli_run_runtime_error(tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]) -> None:
    src_file = tmp_path / "err.mv"
    src_file.write_text("print 10; print 1 / 0;", encoding="utf-8")
    ret = main(["run", str(src_file)])
    captured = capsys.readouterr()
    assert ret == 3
    assert captured.out == ""
    assert "Error:" in captured.err


# 49. CLI: file unreadable exit code 2
def test_cli_unreadable_file(capsys: pytest.CaptureFixture[str]) -> None:
    ret = main(["run", "non_existent_file.mv"])
    captured = capsys.readouterr()
    assert ret == 2
    assert captured.out == ""
    assert "Usage error:" in captured.err


# 50. CLI: invalid step limit exit code 2
def test_cli_invalid_step_limit(tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]) -> None:
    src_file = tmp_path / "test.mv"
    src_file.write_text("print 1;", encoding="utf-8")
    ret = main(["run", str(src_file), "--step-limit", "0"])
    captured = capsys.readouterr()
    assert ret == 2
    assert captured.out == ""


# 51. CLI: build, exec, disasm pipeline
def test_cli_build_exec_disasm(tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]) -> None:
    src_file = tmp_path / "prog.mv"
    bin_file = tmp_path / "prog.mvm"
    src_file.write_text("print 99;", encoding="utf-8")
    ret_build = main(["build", str(src_file), str(bin_file)])
    assert ret_build == 0
    ret_exec = main(["exec", str(bin_file)])
    assert ret_exec == 0
    captured_exec = capsys.readouterr()
    assert captured_exec.out.strip() == "99"
    ret_disasm = main(["disasm", str(bin_file)])
    assert ret_disasm == 0
    captured_disasm = capsys.readouterr()
    assert "CONST" in captured_disasm.out
    assert "PRINT" in captured_disasm.out


# 52. Complex control flow: if-else-if and while
def test_control_flow() -> None:
    src = """
    let x = 3;
    let acc = 0;
    while (x > 0) {
        acc = acc + x;
        x = x - 1;
    }
    print acc;
    if (acc > 10) {
        print "big";
    } else if (acc == 6) {
        print "six";
    } else {
        print "other";
    }
    """
    assert run_code(src) == ["6", "six"]
