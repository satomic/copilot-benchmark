"""Tests for the microvm toolchain."""

from __future__ import annotations

import struct
import subprocess
import sys
import zlib
from pathlib import Path

import pytest

import microvm
from microvm import (
    OPCODE_NUMBERS,
    OPCODES,
    CompileError,
    Instr,
    LexError,
    ParseError,
    Program,
    SerializationError,
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


def run(src: str, **kwargs: object) -> list[str]:
    return execute(compile_source(src, **kwargs))  # type: ignore[arg-type]


def ops(program: Program) -> list[str]:
    return [instr.op for instr in program.instructions]


# ---------------------------------------------------------------- lexer


def test_tokenize_kinds_and_offsets() -> None:
    tokens = tokenize('let x = 12 + 1.5e3; // comment\nprint "hi";')
    kinds = [(t.kind, t.text) for t in tokens]
    assert kinds == [
        ("KEYWORD", "let"), ("IDENT", "x"), ("OP", "="), ("INT", "12"), ("OP", "+"),
        ("FLOAT", "1.5e3"), ("OP", ";"), ("KEYWORD", "print"), ("STRING", "hi"), ("OP", ";"),
    ]
    assert tokens[3].value == 12 and tokens[5].value == 1500.0
    assert tokens[0].offset == 0 and tokens[1].offset == 4
    assert tokens[7].offset == len("let x = 12 + 1.5e3; // comment\n")


def test_tokenize_string_escapes() -> None:
    (tok,) = tokenize(r'"a\n\t\"\\b"')
    assert tok.kind == "STRING"
    assert tok.value == 'a\n\t"\\b' and tok.text == tok.value


@pytest.mark.parametrize("src", ['"abc', '"a\nb"', r'"\q"', "1.", ".5", "1e3", "@", "1.5.2"])
def test_tokenize_errors(src: str) -> None:
    with pytest.raises(LexError) as info:
        tokenize(src)
    assert isinstance(info.value.offset, int)


def test_tokenize_longest_match_and_case_sensitivity() -> None:
    tokens = tokenize("a==b<=c!=d>=e=f IF")
    assert [t.text for t in tokens if t.kind == "OP"] == ["==", "<=", "!=", ">=", "="]
    assert tokens[-1].kind == "IDENT" and tokens[-1].text == "IF"
    assert tokenize("true")[0].kind == "KEYWORD"


def test_tokenize_no_eof_token() -> None:
    assert tokenize("") == []
    assert tokenize("   // only a comment") == []


# ---------------------------------------------------------------- parser


def test_parse_valid_program() -> None:
    src = """
    let x = 1;
    { x = x + 1; }
    if (x > 1) { print "a"; } else if (x < 0) { print "b"; } else { print "c"; }
    while (x > 0) { x = x - 1; }
    print not -x;
    """
    assert parse(src) is not None


@pytest.mark.parametrize(
    "src",
    [
        "1 < 2 < 3;", "print 1 < 2 < 3;", "let x = 1", "let = 1;", "x + 1;", "print;",
        "if x > 1 { }", "if (true) print 1;", "let x = (1 + 2;", "{ print 1;", "else { }",
        "let x = 1 +;", "print 1 2;", "let let = 1;", "print true ==;",
    ],
)
def test_parse_errors(src: str) -> None:
    with pytest.raises(ParseError) as info:
        parse(src)
    assert isinstance(info.value.offset, int) and info.value.offset >= 0


def test_parse_lex_error_passes_through() -> None:
    with pytest.raises(LexError):
        parse('print "unterminated;')


def test_parse_error_offset_points_at_problem() -> None:
    with pytest.raises(ParseError) as info:
        parse("print 1 < 2 < 3;")
    assert info.value.offset == "print 1 < 2 < 3;".index("<", 9) == 12


# ---------------------------------------------------------------- semantics


def test_arithmetic_types() -> None:
    assert run("print 1 + 2; print 1 + 2.0; print 2 * 3; print 2.5 * 2; print 5 - 7;") == [
        "3", "3.0", "6", "5.0", "-2",
    ]


def test_string_concatenation_and_mixed_error() -> None:
    assert run('print "foo" + "bar";') == ["foobar"]
    with pytest.raises(VMRuntimeError):
        run('print "a" + 1;')
    with pytest.raises(VMRuntimeError):
        run('print "a" - "b";')


def test_division_always_float_and_modulo() -> None:
    assert run("print 7 / 2; print 4 / 2; print -7 % 3; print 7 % 3;") == ["3.5", "2.0", "2", "1"]
    with pytest.raises(VMRuntimeError):
        run("print 7.0 % 2;")


def test_division_and_modulo_by_zero() -> None:
    with pytest.raises(VMRuntimeError):
        run("print 1 / 0;")
    with pytest.raises(VMRuntimeError):
        run("print 1.0 / 0.0;")
    with pytest.raises(VMRuntimeError):
        run("print 1 % 0;")


def test_unary_minus_requires_number() -> None:
    assert run("print -3; print -2.5; print - -1;") == ["-3", "-2.5", "1"]
    with pytest.raises(VMRuntimeError):
        run("print -true;")
    with pytest.raises(VMRuntimeError):
        run('print -"x";')


def test_bool_is_not_a_number() -> None:
    with pytest.raises(VMRuntimeError):
        run("print true + 1;")
    with pytest.raises(VMRuntimeError):
        run("print true * true;")


def test_equality_semantics() -> None:
    assert run(
        'print 1 == 1.0; print true == 1; print "1" == 1; print true != 1; '
        'print "a" == "a"; print 1 != 2; print false == false;'
    ) == ["true", "false", "false", "true", "true", "true", "true"]


def test_ordering_semantics() -> None:
    assert run('print 1 < 2.5; print 2 >= 2; print "a" < "b"; print "b" <= "a";') == [
        "true", "true", "true", "false",
    ]
    for src in ('print 1 < "a";', "print true < false;", "print 1 > true;"):
        with pytest.raises(VMRuntimeError):
            run(src)


def test_logic_operators_and_precedence() -> None:
    assert run("print true and false; print true or false; print not true;") == [
        "false", "true", "false",
    ]
    assert run("print not false and false; print false or true and true;") == ["false", "true"]
    assert run("print 1 < 2 and 2 < 3 or false;") == ["true"]


def test_short_circuit_skips_right_operand() -> None:
    assert run("print false and (1 / 0 == 0); print true or (1 / 0 == 0);") == ["false", "true"]
    assert run("print true or true and 5; print false and 5 or true;") == ["true", "true"]


def test_logic_operands_must_be_bool() -> None:
    for src in ("print true and 5;", "print false or 0;", "print 1 and true;", "print not 1;"):
        with pytest.raises(VMRuntimeError):
            run(src)


def test_if_while_condition_must_be_bool() -> None:
    with pytest.raises(VMRuntimeError):
        run("if (1) { print 1; }")
    with pytest.raises(VMRuntimeError):
        run("while (1) { print 1; }")


def test_print_rendering() -> None:
    assert run('print 4 / 2; print true; print false; print "q\\"x\\n"; print 10;') == [
        "2.0", "true", "false", 'q"x\n', "10",
    ]


def test_control_flow() -> None:
    src = """
    let x = 3;
    if (x > 5) { print "big"; } else if (x > 2) { print "mid"; } else { print "small"; }
    let total = 0;
    while (x > 0) { total = total + x; x = x - 1; }
    print total;
    if (x == 0) { print "done"; }
    if (x != 0) { print "no"; } else { print "yes"; }
    """
    assert run(src) == ["mid", "6", "done", "yes"]


def test_blocks_do_not_scope() -> None:
    assert run("{ let x = 1; } print x; if (true) { let y = 2; } print y;") == ["1", "2"]


def test_compile_errors_for_names() -> None:
    with pytest.raises(CompileError):
        compile_source("let x = 1; let x = 2;")
    with pytest.raises(CompileError):
        compile_source("x = 1;")
    with pytest.raises(CompileError):
        compile_source("print x;")
    with pytest.raises(CompileError):
        compile_source("let x = 1; { let x = 2; }")


def test_never_assigned_variable_is_runtime_error() -> None:
    program = compile_source("if (false) { let x = 1; } print x;")
    assert "x" in program.names
    with pytest.raises(VMRuntimeError) as info:
        execute(program)
    assert "x" in str(info.value)


# ---------------------------------------------------------------- bytecode


def test_opcode_table() -> None:
    assert len(OPCODES) == 21 and OPCODES[0] == "CONST" and OPCODES[-1] == "HALT"
    assert OPCODE_NUMBERS["CONST"] == 1 and OPCODE_NUMBERS["HALT"] == 21
    assert len(set(OPCODE_NUMBERS.values())) == 21


def test_print_literal_is_three_instructions() -> None:
    program = compile_source("print 1;")
    assert program.instructions == [Instr("CONST", 0), Instr("PRINT", None), Instr("HALT", None)]
    assert program.constants == [1]


def test_single_trailing_halt() -> None:
    program = compile_source("let x = 1; while (x < 3) { x = x + 1; } if (x == 3) { print x; }")
    assert ops(program).count("HALT") == 1 and ops(program)[-1] == "HALT"
    for instr in program.instructions:
        assert (instr.arg is None) == (instr.op not in {"CONST", "LOAD", "STORE", "JUMP", "JUMP_IF_FALSE"})


def test_constant_pool_dedup() -> None:
    program = compile_source("print 1; print 1.0; print true; print 1; print true; print 1.0;")
    assert program.constants == [1, 1.0, True]
    assert [type(c) for c in program.constants] == [int, float, bool]
    program = compile_source('print "a"; print "a"; print "b";')
    assert program.constants == ["a", "b"]


def test_short_circuit_uses_jumps() -> None:
    program = compile_source("print true and false; print true or false;")
    assert "JUMP_IF_FALSE" in ops(program) and "JUMP" in ops(program)
    for instr in program.instructions:
        if instr.op in ("JUMP", "JUMP_IF_FALSE"):
            assert 0 <= instr.arg < len(program.instructions)


def test_names_in_declaration_order() -> None:
    program = compile_source("let b = 1; { let a = 2; } let c = 3;")
    assert program.names == ["b", "a", "c"]


# ---------------------------------------------------------------- vm


def test_step_limit() -> None:
    with pytest.raises(StepLimitError):
        execute(compile_source("while (true) {}"), step_limit=1000)
    assert issubclass(StepLimitError, VMRuntimeError)
    with pytest.raises(VMRuntimeError):
        execute(compile_source("while (true) {}"), step_limit=1000)


def test_step_limit_boundary() -> None:
    program = compile_source("print 1;")  # exactly 3 steps
    assert execute(program, step_limit=3) == ["1"]
    with pytest.raises(StepLimitError):
        execute(program, step_limit=2)


@pytest.mark.parametrize("bad", [0, -1, True, 1.5, "10", None])
def test_step_limit_validation(bad: object) -> None:
    with pytest.raises(ValueError):
        execute(compile_source("print 1;"), step_limit=bad)  # type: ignore[arg-type]


def test_output_collected_before_error() -> None:
    with pytest.raises(VMRuntimeError):
        run("print 1; print 1 / 0;")


# ---------------------------------------------------------------- optimizer


def test_fold_reduces_instruction_count() -> None:
    optimized = compile_source("print 1 + 2 * 3;", optimize=True)
    plain = compile_source("print 1 + 2 * 3;")
    assert ops(optimized) == ["CONST", "PRINT", "HALT"] and optimized.constants == [7]
    assert len(plain.instructions) > 3
    assert execute(optimized) == execute(plain) == ["7"]


def test_fold_preserves_semantics() -> None:
    src = (
        'print -(2 + 3) * 2.0; print not (1 < 2); print "a" + "b"; print 7 / 2; print -7 % 3; '
        "print true and false; print false or true; print 1 == 1.0; print true == 1;"
    )
    assert run(src, optimize=True) == run(src)
    assert ops(compile_source(src, optimize=True)) == ["CONST", "PRINT"] * 9 + ["HALT"]


def test_fold_does_not_fold_failing_operations() -> None:
    with pytest.raises(VMRuntimeError):
        run("print 1 / 0;", optimize=True)
    with pytest.raises(VMRuntimeError):
        run('print "a" + 1;', optimize=True)
    with pytest.raises(VMRuntimeError):
        run("print -true;", optimize=True)
    with pytest.raises(VMRuntimeError):
        run("print 1 % 0;", optimize=True)
    assert "DIV" in ops(compile_source("print 1 / 0;", optimize=True))


def test_fold_logic_keeps_bool_check() -> None:
    with pytest.raises(VMRuntimeError):
        run("let y = true and 5;", optimize=True)
    with pytest.raises(VMRuntimeError):
        run("let y = false or 5;", optimize=True)
    assert "JUMP_IF_FALSE" in ops(compile_source("let y = true and 5;", optimize=True))


def test_fold_logic_short_circuit_cases() -> None:
    program = compile_source("print false and (1 / 0 == 0); print true or 5;", optimize=True)
    assert ops(program) == ["CONST", "PRINT", "CONST", "PRINT", "HALT"]
    assert execute(program) == ["false", "true"]


def test_fold_constants_direct() -> None:
    from microvm.parser import Literal, Module, Print

    tree = fold_constants(parse("print 2 * (3 + 4) == 14;"))
    assert isinstance(tree, Module)
    stmt = tree.stmts[0]
    assert isinstance(stmt, Print) and isinstance(stmt.expr, Literal) and stmt.expr.value is True


def test_fold_inside_control_flow() -> None:
    src = "let x = 0; while (x < 2 + 1) { x = x + 1 * 1; } if (1 < 2) { print x; } else { print 0; }"
    assert run(src, optimize=True) == ["3"]
    assert len(compile_source(src, optimize=True).instructions) < len(compile_source(src).instructions)


# ---------------------------------------------------------------- serializer

SAMPLE = (
    'let x = 5; let s = "h\\n"; let f = 2.5; let b = true; let n = -3; '
    "while (x > 0) { x = x - 1; } print x; print s; print f; print b; print n;"
)


def test_round_trip() -> None:
    program = compile_source(SAMPLE)
    data = dumps(program)
    assert data[:4] == b"MVM1" and data[4] == 1
    restored = loads(data)
    assert restored.constants == program.constants
    assert [type(c) for c in restored.constants] == [type(c) for c in program.constants]
    assert restored.names == program.names and restored.instructions == program.instructions
    assert execute(restored) == execute(program)


def test_dumps_deterministic_and_layout() -> None:
    program = compile_source("print 1;")
    data = dumps(program)
    assert data == dumps(compile_source("print 1;"))
    body = (
        b"\x01" + b"\x00\x00" + b"\x00\x01" + b"\x01" + struct.pack(">q", 1) + b"\x00\x00\x00\x03"
        + b"\x01\x00\x00\x00\x00" + b"\x13\xff\xff\xff\xff" + b"\x15\xff\xff\xff\xff"
    )
    assert data == b"MVM1" + body + struct.pack(">I", zlib.crc32(body))


def test_dumps_int_range() -> None:
    dumps(Program([2**63 - 1, -(2**63)], [], [Instr("HALT", None)]))
    with pytest.raises(SerializationError):
        dumps(Program([2**63], [], [Instr("HALT", None)]))
    with pytest.raises(SerializationError):
        dumps(Program([-(2**63) - 1], [], [Instr("HALT", None)]))


def test_dumps_rejects_bad_instructions() -> None:
    with pytest.raises(SerializationError):
        dumps(Program([], [], [Instr("BOGUS", None)]))
    with pytest.raises(SerializationError):
        dumps(Program([], [], [Instr("CONST", None), Instr("HALT", None)]))
    with pytest.raises(SerializationError):
        dumps(Program([], [], [Instr("HALT", 0)]))


def _with_checksum(body: bytes) -> bytes:
    return b"MVM1" + body + struct.pack(">I", zlib.crc32(body))


def _body(data: bytes) -> bytes:
    return data[4:-4]


def test_loads_bad_magic_and_version() -> None:
    data = dumps(compile_source("print 1;"))
    with pytest.raises(SerializationError):
        loads(b"MVM2" + data[4:])
    with pytest.raises(SerializationError):
        loads(_with_checksum(b"\x02" + _body(data)[1:]))
    with pytest.raises(SerializationError):
        loads(b"")


def test_loads_checksum_mismatch_and_truncation() -> None:
    data = dumps(compile_source("print 1;"))
    corrupted = bytearray(data)
    corrupted[10] ^= 0xFF
    with pytest.raises(SerializationError):
        loads(bytes(corrupted))
    for cut in range(1, len(data)):
        with pytest.raises(SerializationError):
            loads(data[:cut])


def test_loads_trailing_bytes() -> None:
    data = dumps(compile_source("print 1;"))
    with pytest.raises(SerializationError):
        loads(data + b"\x00")
    with pytest.raises(SerializationError):
        loads(_with_checksum(_body(data) + b"\x00"))


def test_loads_unknown_constant_tag_and_bad_bool() -> None:
    body = bytearray(_body(dumps(compile_source("print true;"))))
    tag_pos = 1 + 2 + 2
    assert body[tag_pos] == 4
    bad_bool = bytearray(body)
    bad_bool[tag_pos + 1] = 2
    with pytest.raises(SerializationError):
        loads(_with_checksum(bytes(bad_bool)))
    bad_tag = bytearray(body)
    bad_tag[tag_pos] = 9
    with pytest.raises(SerializationError):
        loads(_with_checksum(bytes(bad_tag)))


def test_loads_unknown_opcode_and_arg_mismatch() -> None:
    body = bytearray(_body(dumps(compile_source("print 1;"))))
    first_instr = len(body) - 3 * 5
    bad_op = bytearray(body)
    bad_op[first_instr] = 22
    with pytest.raises(SerializationError):
        loads(_with_checksum(bytes(bad_op)))
    bad_op[first_instr] = 0
    with pytest.raises(SerializationError):
        loads(_with_checksum(bytes(bad_op)))
    missing_arg = bytearray(body)
    missing_arg[first_instr + 1:first_instr + 5] = b"\xff\xff\xff\xff"
    with pytest.raises(SerializationError):
        loads(_with_checksum(bytes(missing_arg)))
    extra_arg = bytearray(body)
    extra_arg[first_instr + 6:first_instr + 10] = b"\x00\x00\x00\x00"
    with pytest.raises(SerializationError):
        loads(_with_checksum(bytes(extra_arg)))


def test_loads_truncated_length_field_with_valid_checksum() -> None:
    body = bytearray(_body(dumps(compile_source("print 1;"))))
    body[1:3] = b"\x00\x05"  # claims five names but has none
    with pytest.raises(SerializationError):
        loads(_with_checksum(bytes(body)))


def test_round_trip_special_values() -> None:
    program = compile_source('print 1.5e300 * 1.5e300; print "\u00e9"; print 0.1 + 0.2;')
    program.constants.append("héllo ☃")
    assert loads(dumps(program)).constants == program.constants
    assert execute(loads(dumps(program))) == execute(program)


# ---------------------------------------------------------------- disassembler


def test_disassemble_exact() -> None:
    assert disassemble(compile_source("print 1;")) == "0000 CONST 0  ; 1\n0001 PRINT\n0002 HALT\n"


def test_disassemble_constants_rendering() -> None:
    text = disassemble(compile_source('print 2.0; print true; print false; print "a\\"b\\\\\\n\\t";'))
    lines = text.splitlines()
    assert lines[0] == "0000 CONST 0  ; 2.0"
    assert lines[2] == "0002 CONST 1  ; true"
    assert lines[4] == "0004 CONST 2  ; false"
    assert lines[6] == '0006 CONST 3  ; "a\\"b\\\\\\n\\t"'
    assert text.endswith("\n") and text.count("\n") == len(lines)


def test_disassemble_jumps_and_loads() -> None:
    lines = disassemble(compile_source("let x = 1; while (x > 0) { x = x - 1; }")).splitlines()
    assert lines[1] == "0001 STORE 0"
    assert lines[2] == "0002 LOAD 0"
    assert any(line.split()[1] == "JUMP_IF_FALSE" for line in lines)
    assert all(len(line.split()[0]) == 4 for line in lines)


# ---------------------------------------------------------------- package


def test_public_api() -> None:
    assert len(microvm.__all__) == 19
    for name in microvm.__all__:
        assert hasattr(microvm, name)


def test_error_hierarchy() -> None:
    from microvm.errors import MicroVMError

    for cls in (LexError, ParseError, CompileError, SerializationError, VMRuntimeError):
        assert issubclass(cls, MicroVMError)
    assert issubclass(StepLimitError, VMRuntimeError)
    assert "StepLimitError" not in microvm.__all__


# ---------------------------------------------------------------- cli


def test_cli_run(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    src = tmp_path / "t.mv"
    src.write_text("let x = 5; print x; print 8 / 2;", encoding="utf-8")
    assert main(["run", str(src)]) == 0
    assert capsys.readouterr().out == "5\n4.0\n"
    assert main(["run", str(src), "--optimize", "--step-limit", "50"]) == 0
    assert capsys.readouterr().out == "5\n4.0\n"


def test_cli_build_exec_disasm(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    src = tmp_path / "t.mv"
    out = tmp_path / "t.mvb"
    src.write_text('print "hello"; print 1 + 2;', encoding="utf-8")
    assert main(["build", str(src), str(out), "--optimize"]) == 0
    assert capsys.readouterr().out == ""
    assert loads(out.read_bytes()).constants == ["hello", 3]
    assert main(["exec", str(out)]) == 0
    assert capsys.readouterr().out == "hello\n3\n"
    assert main(["disasm", str(out)]) == 0
    assert capsys.readouterr().out == disassemble(loads(out.read_bytes()))


def test_cli_usage_errors(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    src = tmp_path / "t.mv"
    src.write_text("print 1;", encoding="utf-8")
    assert main([]) == 2
    assert main(["bogus"]) == 2
    assert main(["run"]) == 2
    assert main(["run", str(tmp_path / "missing.mv")]) == 2
    assert main(["exec", str(tmp_path / "missing.mvb")]) == 2
    assert main(["run", str(src), "--step-limit", "0"]) == 2
    assert main(["run", str(src), "--step-limit", "abc"]) == 2
    assert capsys.readouterr().out == ""


def test_cli_microvm_errors_no_stdout(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    src = tmp_path / "t.mv"
    src.write_text("print 1; print 2; print 1 / 0;", encoding="utf-8")
    assert main(["run", str(src)]) == 3
    captured = capsys.readouterr()
    assert captured.out == "" and "VMRuntimeError" in captured.err
    src.write_text("print 1 < 2 < 3;", encoding="utf-8")
    assert main(["run", str(src)]) == 3
    src.write_text("while (true) {}", encoding="utf-8")
    assert main(["run", str(src), "--step-limit", "10"]) == 3
    bad = tmp_path / "bad.mvb"
    bad.write_bytes(b"garbage")
    assert main(["exec", str(bad)]) == 3
    assert main(["disasm", str(bad)]) == 3
    assert capsys.readouterr().out == ""


def test_cli_subprocess_exit_code(tmp_path: Path) -> None:
    src = tmp_path / "t.mv"
    src.write_text("let x = 5; print x; print 8 / 2;", encoding="utf-8")
    root = Path(__file__).resolve().parent.parent
    result = subprocess.run(
        [sys.executable, "-m", "microvm", "run", str(src)],
        cwd=root, capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0 and result.stdout.splitlines() == ["5", "4.0"]
    result = subprocess.run(
        [sys.executable, "-m", "microvm", "run", str(tmp_path / "nope.mv")],
        cwd=root, capture_output=True, text=True, check=False,
    )
    assert result.returncode == 2
