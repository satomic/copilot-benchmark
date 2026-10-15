from __future__ import annotations

from pathlib import Path
import struct
import zlib
import pytest

import microvm
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
from microvm.__main__ import main as cli_main
from microvm.errors import StepLimitError


def run_src(src: str, *, optimize: bool = False, step_limit: int = 100_000) -> list[str]:
    prog = compile_source(src, optimize=optimize)
    return execute(prog, step_limit=step_limit)


def test_exports_and_all() -> None:
    expected = {
        "tokenize", "Token", "parse", "compile_source", "Program", "Instr",
        "fold_constants", "execute", "dumps", "loads", "disassemble",
        "OPCODES", "OPCODE_NUMBERS", "MicroVMError", "LexError", "ParseError",
        "CompileError", "SerializationError", "VMRuntimeError",
    }
    assert len(microvm.__all__) == 19
    assert set(microvm.__all__) == expected
    for name in expected:
        assert hasattr(microvm, name)


def test_opcodes_contract() -> None:
    assert len(OPCODES) == 21
    assert OPCODES[0] == "CONST"
    assert OPCODES[-1] == "HALT"
    assert OPCODE_NUMBERS["CONST"] == 1
    assert OPCODE_NUMBERS["HALT"] == 21


def test_lexer_basic_tokens() -> None:
    src = 'let x = 42; // comment\nprint "hi\\n\\t\\"\\\\";'
    toks = tokenize(src)
    assert toks[0] == Token("KEYWORD", "let", "let", 0)
    assert toks[1] == Token("IDENT", "x", "x", 4)
    assert toks[2] == Token("OP", "=", "=", 6)
    assert toks[3] == Token("INT", "42", 42, 8)
    assert toks[4] == Token("OP", ";", ";", 10)
    assert toks[5] == Token("KEYWORD", "print", "print", 23)
    assert toks[6] == Token("STRING", 'hi\n\t"\\', 'hi\n\t"\\', 29)
    assert toks[7] == Token("OP", ";", ";", 41)


def test_lexer_floats_and_exponents() -> None:
    toks = tokenize("1.5 1.5e3 2.0E-2 0.25e+1")
    assert [t.kind for t in toks] == ["FLOAT", "FLOAT", "FLOAT", "FLOAT"]
    assert [t.value for t in toks] == [1.5, 1500.0, 0.02, 2.5]


@pytest.mark.parametrize(
    "bad_src,expected_offset",
    [
        ("1.", 0),
        (".5", 0),
        ("  1.e2", 2),
        ("1.5e", 0),
        ("1.5e+", 0),
        ('"unterminated', 0),
        ('"bad\\xescape"', 0),
        ('"line\nbreak"', 0),
        ("let a = @;", 8),
    ],
)
def test_lexer_errors(bad_src: str, expected_offset: int) -> None:
    with pytest.raises(LexError) as exc_info:
        tokenize(bad_src)
    assert exc_info.value.offset == expected_offset


def test_lexer_case_sensitivity() -> None:
    toks = tokenize("IF True let while WHILE")
    assert [t.kind for t in toks] == ["IDENT", "IDENT", "KEYWORD", "KEYWORD", "IDENT"]


def test_lexer_longest_match_operators() -> None:
    toks = tokenize("= == != < <= > >= + - * / % ( ) { } ;")
    assert [t.text for t in toks] == [
        "=", "==", "!=", "<", "<=", ">", ">=", "+", "-", "*", "/", "%",
        "(", ")", "{", "}", ";"
    ]


@pytest.mark.parametrize(
    "bad_src",
    [
        "let x;",
        "let 123 = 4;",
        "let let = 1;",
        "1 < 2 < 3;",
        "print 1 == 2 == 3;",
        "if x > 0 { print 1; }",
        "if (x > 0) print 1;",
        "if (true) { print 1; } else print 2;",
        "while true { print 1; }",
        "print 1",
        "{ print 1; ",
        "print ();",
    ],
)
def test_parser_errors(bad_src: str) -> None:
    with pytest.raises(ParseError) as exc_info:
        parse(bad_src)
    assert isinstance(exc_info.value.offset, int)
    assert exc_info.value.offset >= 0


def test_arithmetic_int_and_float() -> None:
    src = """
    print 2 + 3 * 4;
    print (2 + 3) * 4;
    print 10 - 3 - 2;
    print 1 + 2.5;
    print 2.0 * 3;
    print -5 + 2;
    print -2.5;
    """
    assert run_src(src) == ["14", "20", "5", "3.5", "6.0", "-3", "-2.5"]


def test_division_and_modulo() -> None:
    src = """
    print 7 / 2;
    print 4 / 2;
    print -7 % 3;
    print 7 % -3;
    print 10 % 3;
    """
    assert run_src(src) == ["3.5", "2.0", "2", "-2", "1"]


def test_string_concatenation() -> None:
    src = 'print "hello" + " " + "world";'
    assert run_src(src) == ["hello world"]


@pytest.mark.parametrize(
    "bad_runtime_src",
    [
        'print "a" + 1;',
        'print 1 + "a";',
        "print true + 1;",
        "print false - 1;",
        "print true * 2;",
        "print 1 / 0;",
        "print 1.0 / 0.0;",
        "print 5 % 0;",
        "print 5.0 % 2;",
        "print 5 % 2.0;",
        "print -true;",
        'print -"abc";',
        "print not 0;",
        'print not "";',
    ],
)
def test_arithmetic_and_unary_type_errors(bad_runtime_src: str) -> None:
    with pytest.raises(VMRuntimeError):
        run_src(bad_runtime_src)


def test_equality_semantics() -> None:
    src = """
    print 1 == 1;
    print 1 == 1.0;
    print 1 != 2.0;
    print true == 1;
    print false == 0;
    print false == 0.0;
    print true != 1;
    print "a" == "a";
    print "a" == 1;
    print true == true;
    print true == false;
    """
    assert run_src(src) == [
        "true", "true", "true", "false", "false", "false",
        "true", "true", "false", "true", "false",
    ]


def test_ordering_comparisons() -> None:
    src = """
    print 1 < 2.0;
    print 2.0 <= 2;
    print 3 > 1.5;
    print 3.0 >= 3;
    print "abc" < "abd";
    print "b" > "a";
    print "a" <= "a";
    print "z" >= "a";
    """
    assert run_src(src) == ["true"] * 8


@pytest.mark.parametrize(
    "bad_cmp_src",
    [
        "print true < false;",
        "print true <= 1;",
        "print 0 < true;",
        'print "1" < 2;',
        'print 1 >= "1";',
        'print "a" > true;',
    ],
)
def test_ordering_comparison_errors(bad_cmp_src: str) -> None:
    with pytest.raises(VMRuntimeError):
        run_src(bad_cmp_src)


def test_short_circuit_and_or() -> None:
    src = """
    print false and (1 / 0 == 0);
    print true or (1 / 0 == 0);
    print false and "not_a_bool";
    print true or 12345;
    print true and true;
    print true and false;
    print false or true;
    print false or false;
    """
    assert run_src(src) == [
        "false", "true", "false", "true", "true", "false", "true", "false"
    ]


@pytest.mark.parametrize(
    "bad_logic_src",
    [
        "print 1 and true;",
        "print true and 5;",
        "print 0 or false;",
        "print false or 5;",
        'print "x" and false;',
    ],
)
def test_logic_strict_bool_errors(bad_logic_src: str) -> None:
    with pytest.raises(VMRuntimeError):
        run_src(bad_logic_src)


def test_variables_and_global_block_scope() -> None:
    src = """
    let x = 10;
    {
        let y = x + 5;
        x = y * 2;
    }
    print x;
    print y;
    """
    assert run_src(src) == ["30", "15"]


def test_if_else_and_while() -> None:
    src = """
    let n = 4;
    let acc = 0;
    while (n > 0) {
        if (n == 3) {
            acc = acc + 100;
        } else if (n == 2) {
            acc = acc + 10;
        } else {
            acc = acc + 1;
        }
        n = n - 1;
    }
    print acc;
    """
    assert run_src(src) == ["112"]


def test_non_bool_conditions_fail() -> None:
    with pytest.raises(VMRuntimeError):
        run_src("if (1) { print 1; }")
    with pytest.raises(VMRuntimeError):
        run_src("while (0) { print 1; }")


def test_compile_errors_for_variables() -> None:
    with pytest.raises(CompileError):
        compile_source("let x = 1; let x = 2;")
    with pytest.raises(CompileError):
        compile_source("let x = 1; { let x = 2; }")
    with pytest.raises(CompileError):
        compile_source("x = 1;")
    with pytest.raises(CompileError):
        compile_source("print unknown_var;")


def test_unassigned_variable_at_runtime() -> None:
    src = """
    if (false) {
        let secret = 42;
    }
    print secret;
    """
    with pytest.raises(VMRuntimeError) as exc_info:
        run_src(src)
    assert "secret" in str(exc_info.value)


def test_constant_pool_deduplication() -> None:
    src = """
    print 1;
    print 1.0;
    print true;
    print 1;
    print 1.0;
    print true;
    print "s";
    print "s";
    """
    prog = compile_source(src)
    assert len(prog.constants) == 4
    types_and_vals = [(type(c), c) for c in prog.constants]
    assert types_and_vals == [(int, 1), (float, 1.0), (bool, True), (str, "s")]


def test_print_literal_instruction_count_and_halt() -> None:
    prog = compile_source("print 1;")
    assert len(prog.instructions) == 3
    assert [i.op for i in prog.instructions] == ["CONST", "PRINT", "HALT"]
    assert sum(1 for i in prog.instructions if i.op == "HALT") == 1


def test_disassemble_exact_format() -> None:
    prog = compile_source("print 1;")
    assert disassemble(prog) == "0000 CONST 0  ; 1\n0001 PRINT\n0002 HALT\n"


def test_disassemble_all_constant_types() -> None:
    prog = compile_source('print true; print 2.5; print "a\\nb\\t\\"\\\\";')
    text = disassemble(prog)
    assert '0000 CONST 0  ; true\n' in text
    assert '0002 CONST 1  ; 2.5\n' in text
    assert '0004 CONST 2  ; "a\\nb\\t\\"\\\\"\n' in text


def test_optimizer_folds_expressions_to_3_instrs() -> None:
    src = "print 1 + 2 * 3;"
    unopt = compile_source(src, optimize=False)
    opt = compile_source(src, optimize=True)
    assert len(unopt.instructions) > 3
    assert len(opt.instructions) == 3
    assert opt.constants == [7]
    assert execute(opt) == ["7"]


def test_optimizer_folds_comparisons_and_logic() -> None:
    src = """
    print (1 < 2.0) and (not false);
    print ("a" + "b" == "ab") or false;
    print false and (1 / 0 == 0);
    print true or (1 / 0 == 0);
    """
    opt = compile_source(src, optimize=True)
    assert execute(opt) == ["true", "true", "false", "true"]
    assert len(opt.instructions) == 9  # 4 * (CONST, PRINT) + HALT


@pytest.mark.parametrize(
    "unsafe_src",
    [
        "print 1 / 0;",
        "print 5 % 0;",
        'print "a" + 1;',
        "let y = true and 5;",
        "let y = false or 5;",
        "let x = 5; print true and x;",
        "let x = 5; print false or x;",
        "print true < false;",
        "print -true;",
        "print not 1;",
    ],
)
def test_optimizer_preserves_runtime_errors(unsafe_src: str) -> None:
    prog = compile_source(unsafe_src, optimize=True)
    with pytest.raises(VMRuntimeError):
        execute(prog)


def test_optimizer_preserves_undeclared_var_compile_error() -> None:
    with pytest.raises(CompileError):
        compile_source("print false and undeclared_var;", optimize=True)


def test_step_limit_enforcement() -> None:
    prog = compile_source("while (true) {}")
    with pytest.raises(StepLimitError):
        execute(prog, step_limit=50)


@pytest.mark.parametrize("bad_limit", [0, -10, True, False, 1.5, "100"])
def test_step_limit_validation(bad_limit: object) -> None:
    prog = compile_source("print 1;")
    with pytest.raises(ValueError):
        execute(prog, step_limit=bad_limit)  # type: ignore[arg-type]


def test_serializer_round_trip_and_determinism() -> None:
    src = """
    let a = -9223372036854775808;
    let b = 9223372036854775807;
    let c = 3.14159;
    let d = "hello 🌍";
    let e = true;
    let f = false;
    if (e and not f) {
        print a;
        print b;
        print c;
        print d;
    }
    """
    prog = compile_source(src, optimize=True)
    b1 = dumps(prog)
    b2 = dumps(prog)
    assert b1 == b2
    loaded = loads(b1)
    assert execute(loaded) == execute(prog)


def test_serializer_int_out_of_range() -> None:
    prog = Program(constants=[1 << 63], names=[], instructions=[Instr("HALT", None)])
    with pytest.raises(SerializationError):
        dumps(prog)
    prog_neg = Program(constants=[-(1 << 63) - 1], names=[], instructions=[Instr("HALT", None)])
    with pytest.raises(SerializationError):
        dumps(prog_neg)


def test_serializer_corruption_cases() -> None:
    prog = compile_source('let x = 1; print x; print "hi"; print true;')
    valid = dumps(prog)

    # 1. Bad magic
    with pytest.raises(SerializationError):
        loads(b"MVM2" + valid[4:])

    # 2. Checksum mismatch
    corrupted = bytearray(valid)
    corrupted[-1] ^= 0xFF
    with pytest.raises(SerializationError):
        loads(bytes(corrupted))

    # 3. Truncated input
    with pytest.raises(SerializationError):
        loads(valid[:-1])
    with pytest.raises(SerializationError):
        loads(b"MVM1")

    def repack_with_crc(body: bytes) -> bytes:
        crc = zlib.crc32(body) & 0xFFFFFFFF
        return b"MVM1" + body + struct.pack(">I", crc)

    # 4. Unsupported version
    bad_ver_body = b"\x02" + valid[5:-4]
    with pytest.raises(SerializationError):
        loads(repack_with_crc(bad_ver_body))

    # 5. Trailing bytes after instructions (inside checksummed body)
    trailing_body = valid[4:-4] + b"\x00"
    with pytest.raises(SerializationError):
        loads(repack_with_crc(trailing_body))

    # 6. Unknown constant tag
    bad_tag_body = struct.pack(">BHH", 1, 0, 1) + b"\x99\x00" + struct.pack(">I", 0)
    with pytest.raises(SerializationError):
        loads(repack_with_crc(bad_tag_body))

    # 7. Invalid BOOL payload (2 instead of 0/1)
    bad_bool_body = struct.pack(">BHH", 1, 0, 1) + b"\x04\x02" + struct.pack(">I", 0)
    with pytest.raises(SerializationError):
        loads(repack_with_crc(bad_bool_body))

    # 8. Unknown opcode number
    bad_op_body = struct.pack(">BHHI", 1, 0, 0, 1) + struct.pack(">BI", 99, 0xFFFFFFFF)
    with pytest.raises(SerializationError):
        loads(repack_with_crc(bad_op_body))

    # 9. Arg opcode with 0xFFFFFFFF
    bad_arg_body = struct.pack(">BHHI", 1, 0, 0, 1) + struct.pack(">BI", 1, 0xFFFFFFFF)
    with pytest.raises(SerializationError):
        loads(repack_with_crc(bad_arg_body))

    # 10. No-arg opcode with non-0xFFFFFFFF arg
    bad_noarg_body = struct.pack(">BHHI", 1, 0, 0, 1) + struct.pack(">BI", 21, 0)
    with pytest.raises(SerializationError):
        loads(repack_with_crc(bad_noarg_body))


def test_cli_run_build_exec_disasm(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    src_file = tmp_path / "prog.mv"
    bin_file = tmp_path / "prog.mvm"
    src_file.write_text("let x = 5; print x; print 8 / 2;\n", encoding="utf-8")

    assert cli_main(["run", str(src_file)]) == 0
    captured = capsys.readouterr()
    assert captured.out.splitlines() == ["5", "4.0"]

    assert cli_main(["build", str(src_file), str(bin_file), "--optimize"]) == 0
    capsys.readouterr()

    assert cli_main(["exec", str(bin_file)]) == 0
    captured = capsys.readouterr()
    assert captured.out.splitlines() == ["5", "4.0"]

    assert cli_main(["disasm", str(bin_file)]) == 0
    captured = capsys.readouterr()
    assert "HALT" in captured.out


def test_cli_exit_codes_and_buffered_stdout(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    # Usage errors -> 2
    assert cli_main(["unknown_cmd"]) == 2
    assert cli_main(["run"]) == 2
    assert cli_main(["run", str(tmp_path / "nonexistent.mv")]) == 2

    src_file = tmp_path / "err.mv"
    src_file.write_text("print 1;\nprint 1 / 0;\n", encoding="utf-8")
    assert cli_main(["run", str(src_file), "--step-limit", "0"]) == 2
    assert cli_main(["run", str(src_file), "--step-limit", "abc"]) == 2
    capsys.readouterr()

    # Runtime error midway -> exit code 3, NOTHING on stdout, error on stderr
    assert cli_main(["run", str(src_file)]) == 3
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "VMRuntimeError" in captured.err


def test_lexer_comments_and_empty_input() -> None:
    assert tokenize("") == []
    assert tokenize("   \t\n  ") == []
    assert tokenize("// only a comment") == []
    assert tokenize("// line 1\n// line 2\n") == []


def test_lexer_malformed_numbers_with_letters() -> None:
    with pytest.raises(LexError):
        tokenize("123abc")
    with pytest.raises(LexError):
        tokenize("1.5.2")


def test_parser_empty_program_and_nested_blocks() -> None:
    prog = compile_source("")
    assert execute(prog) == []
    prog2 = compile_source("{ { { print 99; } } }")
    assert execute(prog2) == ["99"]


def test_parser_if_without_else_false_branch() -> None:
    src = """
    let x = 1;
    if (false) {
        x = 2;
    }
    print x;
    """
    assert run_src(src) == ["1"]


def test_parser_else_if_chain_exhausted() -> None:
    src = """
    let x = 10;
    if (x == 1) {
        print "one";
    } else if (x == 2) {
        print "two";
    } else if (x == 3) {
        print "three";
    }
    print "done";
    """
    assert run_src(src) == ["done"]


def test_while_zero_iterations() -> None:
    src = """
    while (false) {
        print "never";
    }
    print "after";
    """
    assert run_src(src) == ["after"]


def test_nested_short_circuit_expressions() -> None:
    src = """
    print (false and (1 / 0 == 0)) or (true and not false);
    print (true or (1 / 0 == 0)) and (false or true);
    print not (false or (false and (1 / 0 == 0)));
    """
    assert run_src(src) == ["true", "true", "true"]


def test_variable_declared_in_later_block_used_after_assigned() -> None:
    src = """
    if (true) {
        let z = 7;
    }
    print z;
    z = z + 1;
    print z;
    """
    assert run_src(src) == ["7", "8"]


def test_variable_declared_below_read_above_raises_runtime_error() -> None:
    src = """
    if (false) {
        print v;
    }
    let v = 123;
    print v;
    """
    assert run_src(src) == ["123"]
    src_fail = """
    if (true) {
        print v;
    }
    let v = 123;
    """
    with pytest.raises(VMRuntimeError):
        run_src(src_fail)


def test_negative_zero_and_float_dedup() -> None:
    src = "print 0.0; print -0.0;"
    prog = compile_source(src)
    assert execute(prog) == ["0.0", "-0.0"]


def test_fold_constants_direct_api() -> None:
    ast = parse("print 2 + 3 * 4;")
    folded = fold_constants(ast)
    assert folded is not None


def test_vm_pop_opcode_execution() -> None:
    prog = Program(
        constants=[10, 20],
        names=[],
        instructions=[
            Instr("CONST", 0),
            Instr("CONST", 1),
            Instr("POP", None),
            Instr("PRINT", None),
            Instr("HALT", None),
        ],
    )
    assert execute(prog) == ["10"]


def test_vm_exact_step_limit_boundary() -> None:
    prog = compile_source("print 1;")
    # 3 instructions: CONST, PRINT, HALT
    assert execute(prog, step_limit=3) == ["1"]
    with pytest.raises(StepLimitError):
        execute(prog, step_limit=2)


def test_serializer_invalid_instr_packing() -> None:
    with pytest.raises(SerializationError):
        dumps(Program(constants=[], names=[], instructions=[Instr("CONST", None)]))
    with pytest.raises(SerializationError):
        dumps(Program(constants=[], names=[], instructions=[Instr("HALT", 1)]))
    with pytest.raises(SerializationError):
        dumps(Program(constants=[], names=[], instructions=[Instr("NOP", None)]))


def test_serializer_huge_claimed_lengths_rejected_by_crc_or_bounds() -> None:
    # Crafted body with huge name count (65535) but empty payload and valid CRC
    body = struct.pack(">BHHI", 1, 65535, 0, 0)
    crc = zlib.crc32(body) & 0xFFFFFFFF
    data = b"MVM1" + body + struct.pack(">I", crc)
    with pytest.raises(SerializationError):
        loads(data)


def test_cli_compile_and_serialization_errors_return_3(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    bad_src = tmp_path / "bad.mv"
    bad_src.write_text("let x = ;", encoding="utf-8")
    assert cli_main(["run", str(bad_src)]) == 3
    assert cli_main(["build", str(bad_src), str(tmp_path / "out.mvm")]) == 3

    bad_bin = tmp_path / "bad.mvm"
    bad_bin.write_bytes(b"NOT_A_VALID_MVM_FILE")
    assert cli_main(["exec", str(bad_bin)]) == 3
    assert cli_main(["disasm", str(bad_bin)]) == 3
    capsys.readouterr()


def test_cli_step_limit_exceeded_returns_3_and_buffers_stdout(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    loop_src = tmp_path / "loop.mv"
    loop_src.write_text('print "before"; while (true) {}', encoding="utf-8")
    assert cli_main(["run", str(loop_src), "--step-limit", "20"]) == 3
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "StepLimitError" in captured.err


def test_error_hierarchy() -> None:
    assert issubclass(LexError, MicroVMError)
    assert issubclass(ParseError, MicroVMError)
    assert issubclass(CompileError, MicroVMError)
    assert issubclass(SerializationError, MicroVMError)
    assert issubclass(VMRuntimeError, MicroVMError)
    assert issubclass(StepLimitError, VMRuntimeError)


def test_precedence_and_associativity() -> None:
    src = """
    print 10 - 4 - 2;
    print 2 + 3 * 4 - 5;
    print not false and false or true;
    print false or true and false;
    """
    assert run_src(src) == ["4", "9", "true", "false"]


def test_unary_minus_precedence() -> None:
    src = """
    print -3 * -2;
    print --5;
    print -(2 + 3);
    """
    assert run_src(src) == ["6", "5", "-5"]


def test_string_escapes_in_execution() -> None:
    src = 'print "line1\\nline2\\tend\\"\\\\";'
    assert run_src(src) == ['line1\nline2\tend"\\']


def test_optimizer_folded_vs_unfolded_equivalence() -> None:
    src = """
    let a = (10 + 20) * 3 - 5;
    let b = 15 / 2;
    let c = 17 % 5;
    let d = "foo" + "bar";
    let e = (a > 50) and (b == 7.5) and (c == 2) and (d == "foobar");
    if (e or false) {
        print a;
        print b;
        print c;
        print d;
        print e;
    }
    """
    assert run_src(src, optimize=False) == run_src(src, optimize=True)


def test_serializer_empty_program() -> None:
    prog = compile_source("")
    raw = dumps(prog)
    loaded = loads(raw)
    assert loaded.constants == []
    assert loaded.names == []
    assert loaded.instructions == [Instr("HALT", None)]
    assert execute(loaded) == []


def test_serializer_trailing_bytes_outside_crc() -> None:
    prog = compile_source("print 1;")
    raw = dumps(prog)
    # Appending bytes after the checksum must fail checksum or trailing check
    with pytest.raises(SerializationError):
        loads(raw + b"\x00")


