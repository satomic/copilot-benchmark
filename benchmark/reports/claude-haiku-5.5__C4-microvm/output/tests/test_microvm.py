"""Tests for the microvm language, compiler, VM, codec and CLI."""

from __future__ import annotations

import dataclasses
import struct
import zlib
from pathlib import Path

import pytest

import microvm
from microvm import (
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
from microvm.opcodes import OPCODE_NUMBERS, OPCODES


def run(src: str, *, optimize: bool = False, step_limit: int = 100_000) -> list[str]:
    return execute(compile_source(src, optimize=optimize), step_limit=step_limit)


def run_error(src: str, *, optimize: bool = False) -> VMRuntimeError:
    with pytest.raises(VMRuntimeError) as info:
        run(src, optimize=optimize)
    return info.value


def test_package_all_has_19_names() -> None:
    assert len(microvm.__all__) == 19
    for name in microvm.__all__:
        assert hasattr(microvm, name)


def test_print_int_and_float_rendering() -> None:
    assert run("print 4 / 2;") == ["2.0"]
    assert run("print 7 / 2;") == ["3.5"]
    assert run("print 42;") == ["42"]


def test_print_bool_and_string() -> None:
    assert run("print true; print false;") == ["true", "false"]
    assert run('print "a\\tb";') == ["a\tb"]


def test_integer_arithmetic_and_precedence() -> None:
    assert run("print 1 + 2 * 3;") == ["7"]
    assert run("print (1 + 2) * 3;") == ["9"]


def test_float_contaminates_arithmetic() -> None:
    assert run("print 1 + 2.0;") == ["3.0"]
    assert run("print 3 * 0.5;") == ["1.5"]


def test_modulo_follows_python_sign_rule() -> None:
    assert run("print -7 % 3;") == ["2"]


def test_modulo_requires_ints() -> None:
    run_error("print 1.0 % 2;")


def test_division_by_zero_is_runtime_error() -> None:
    run_error("print 1 / 0;")
    run_error("print 1 % 0;")


def test_unary_minus_and_type_rule() -> None:
    assert run("print -(2 + 3);") == ["-5"]
    run_error('print -"a";')
    run_error("print -true;")


def test_string_concatenation_and_mixing_error() -> None:
    assert run('print "ab" + "cd";') == ["abcd"]
    run_error('print "a" + 1;')


def test_bool_is_not_a_number() -> None:
    run_error("print true + 1;")
    run_error("print true * 2;")


def test_equality_rules() -> None:
    assert run("print true == 1;") == ["false"]
    assert run("print 1 == 1.0;") == ["true"]
    assert run('print 1 == "1";') == ["false"]
    assert run("print 1 != true;") == ["true"]


def test_ordering_numbers_and_strings() -> None:
    assert run("print 1 < 2.5;") == ["true"]
    assert run('print "abc" < "abd";') == ["true"]
    assert run('print "b" >= "a";') == ["true"]


def test_ordering_rejects_bool_and_mixed() -> None:
    run_error("print true < false;")
    run_error('print 1 < "a";')


def test_comparison_is_not_associative() -> None:
    with pytest.raises(ParseError) as info:
        parse("print 1 < 2 < 3;")
    assert info.value.offset >= 0


def test_and_or_not_require_bool() -> None:
    assert run("print true and false;") == ["false"]
    assert run("print false or true;") == ["true"]
    assert run("print not false;") == ["true"]
    run_error("print true and 5;")
    run_error("print 5 or true;")
    run_error("print not 1;")


def test_and_short_circuits() -> None:
    assert run("print false and (1 / 0 == 0);") == ["false"]


def test_or_short_circuits() -> None:
    assert run("print true or (1 / 0 == 0);") == ["true"]


def test_and_evaluates_right_when_left_true() -> None:
    run_error("print true and (1 / 0 == 0);")


def test_if_condition_must_be_bool() -> None:
    run_error("if (1) { print 1; }")


def test_while_condition_must_be_bool() -> None:
    run_error("while (0) { print 1; }")


def test_if_else_if_chain() -> None:
    src = (
        'let x = 3; if (x > 5) { print "big"; } else if (x > 2) { print "mid"; } '
        'else { print "small"; }'
    )
    assert run(src) == ["mid"]


def test_while_loop_counts_down() -> None:
    assert run("let x = 3; while (x > 0) { print x; x = x - 1; }") == ["3", "2", "1"]


def test_blocks_do_not_create_scope() -> None:
    assert run("if (true) { let y = 2; print y; }") == ["2"]


def test_duplicate_let_is_compile_error() -> None:
    with pytest.raises(CompileError):
        compile_source("let x = 1; let x = 2;")


def test_undeclared_name_is_compile_error() -> None:
    with pytest.raises(CompileError):
        compile_source("print y;")
    with pytest.raises(CompileError):
        compile_source("y = 1;")


def test_keywords_are_case_sensitive() -> None:
    assert run("let IF = 4; print IF;") == ["4"]
    with pytest.raises(ParseError):
        parse("let print = 1;")


def test_never_assigned_variable_read_is_runtime_error() -> None:
    err = run_error("if (false) { let y = 1; } print y;")
    assert "y" in str(err)


def test_declared_in_branch_never_run_compiles() -> None:
    assert run("if (false) { let z = 9; } print 1;") == ["1"]


def test_step_limit_terminates_infinite_loop() -> None:
    with pytest.raises(StepLimitError):
        run("while (true) { }", step_limit=500)


def test_step_limit_must_be_positive_int() -> None:
    program = compile_source("print 1;")
    with pytest.raises(ValueError):
        execute(program, step_limit=0)
    with pytest.raises(ValueError):
        execute(program, step_limit=True)  # type: ignore[arg-type]


def test_step_limit_exact_count_passes() -> None:
    program = compile_source("print 1;")
    assert execute(program, step_limit=3) == ["1"]
    with pytest.raises(StepLimitError):
        execute(program, step_limit=2)


def test_lexer_float_rules() -> None:
    assert tokenize("1.5e3")[0].value == 1500.0
    assert tokenize("2.0E-2")[0].kind == "FLOAT"
    with pytest.raises(LexError):
        tokenize("1.")
    with pytest.raises(LexError):
        tokenize(".5")


def test_lexer_string_escapes_and_errors() -> None:
    assert tokenize('"a\\nb"')[0].value == "a\nb"
    with pytest.raises(LexError):
        tokenize('"\\q"')
    with pytest.raises(LexError):
        tokenize('"open')
    with pytest.raises(LexError) as info:
        tokenize("let a = @;")
    assert info.value.offset == 8


def test_lexer_comments_and_operators() -> None:
    kinds = [t.text for t in tokenize("a == b // trailing\n<= 1")]
    assert kinds == ["a", "==", "b", "<=", "1"]


def test_parse_error_carries_offset() -> None:
    with pytest.raises(ParseError) as info:
        parse("let x = ;")
    assert info.value.offset == 8


def test_constant_pool_dedup_by_type() -> None:
    program = compile_source("print 1; print 1.0; print true; print 1;")
    consts = program.constants
    assert len(consts) == 3
    assert sorted(type(c).__name__ for c in consts) == ["bool", "float", "int"]


def test_print_literal_has_three_instructions() -> None:
    assert len(compile_source("print 1;").instructions) == 3


def test_exactly_one_halt_at_end() -> None:
    program = compile_source("if (true) { print 1; } while (false) { print 2; }")
    ops = [i.op for i in program.instructions]
    assert ops.count("HALT") == 1
    assert ops[-1] == "HALT"


def test_fold_constants_reduces_arithmetic() -> None:
    program = compile_source("print 1 + 2 * 3;", optimize=True)
    assert [i.op for i in program.instructions] == ["CONST", "PRINT", "HALT"]
    assert program.constants[0] == 7


def test_optimize_keeps_division_by_zero_error() -> None:
    program = compile_source("print 1 / 0;", optimize=True)
    assert any(i.op == "DIV" for i in program.instructions)
    with pytest.raises(VMRuntimeError):
        execute(program)


def test_optimize_keeps_and_type_check() -> None:
    with pytest.raises(VMRuntimeError):
        execute(compile_source("let y = true and 5;", optimize=True))


def test_optimize_false_and_folds_without_evaluating() -> None:
    assert run("print false and (1 / 0 == 0);", optimize=True) == ["false"]


def test_fold_constants_is_callable_on_ast() -> None:
    tree = parse("print 2 * 3;")
    folded = fold_constants(tree)
    assert folded is not None


def test_optimized_and_plain_agree() -> None:
    src = 'let a = 4; print a * 2 + 1; print "x" + "y"; print 3 >= 2.5;'
    assert run(src) == run(src, optimize=True)


def test_serializer_round_trip() -> None:
    program = compile_source('let s = "hi\\n"; print s; print 2.5; print -3; print false;')
    data = dumps(program)
    assert data[:4] == b"MVM1"
    assert execute(loads(data)) == execute(program)


def test_serializer_is_deterministic() -> None:
    program = compile_source("print 1 + 1;")
    assert dumps(program) == dumps(program)


def test_serializer_rejects_int_out_of_range() -> None:
    program = Program(constants=[2**63], names=[], instructions=[Instr("CONST", 0), Instr("HALT", None)])
    with pytest.raises(SerializationError):
        dumps(program)


def test_serializer_rejects_bad_magic() -> None:
    data = bytearray(dumps(compile_source("print 1;")))
    data[0] ^= 0xFF
    with pytest.raises(SerializationError):
        loads(bytes(data))


def test_serializer_rejects_checksum_mismatch() -> None:
    data = bytearray(dumps(compile_source("print 1;")))
    data[-5] ^= 0x01
    with pytest.raises(SerializationError):
        loads(bytes(data))


def test_serializer_rejects_truncation() -> None:
    data = dumps(compile_source("print 1;"))
    with pytest.raises(SerializationError):
        loads(data[:-1])
    with pytest.raises(SerializationError):
        loads(data[:3])


def test_serializer_rejects_trailing_bytes() -> None:
    data = dumps(compile_source("print 1;"))
    with pytest.raises(SerializationError):
        loads(data + b"\x00")


def _forge(body: bytes) -> bytes:
    """Build a blob with a valid checksum around a hand-written body."""
    crc = zlib.crc32(body) & 0xFFFFFFFF
    return b"MVM1" + body + struct.pack(">I", crc)


def test_serializer_rejects_unknown_opcode_with_valid_checksum() -> None:
    body = bytes([1]) + struct.pack(">H", 0) + struct.pack(">H", 0)
    body += struct.pack(">I", 1) + bytes([99]) + struct.pack(">I", 0xFFFFFFFF)
    with pytest.raises(SerializationError):
        loads(_forge(body))


def test_serializer_rejects_bad_bool_payload() -> None:
    body = bytes([1]) + struct.pack(">H", 0) + struct.pack(">H", 1)
    body += bytes([0x04, 7]) + struct.pack(">I", 0)
    with pytest.raises(SerializationError):
        loads(_forge(body))


def test_serializer_rejects_unknown_version() -> None:
    body = bytes([2]) + struct.pack(">H", 0) + struct.pack(">H", 0) + struct.pack(">I", 0)
    with pytest.raises(SerializationError):
        loads(_forge(body))


def test_serializer_rejects_arg_on_no_arg_opcode() -> None:
    op_number = OPCODE_NUMBERS["PRINT"]
    body = bytes([1]) + struct.pack(">H", 0) + struct.pack(">H", 0)
    body += struct.pack(">I", 1) + bytes([op_number]) + struct.pack(">I", 5)
    with pytest.raises(SerializationError):
        loads(_forge(body))


def test_serializer_no_arg_encoded_as_ffffffff() -> None:
    data = dumps(compile_source("print 1;"))
    assert struct.pack(">I", 0xFFFFFFFF) in data


def test_disassembly_exact_output() -> None:
    expected = "0000 CONST 0  ; 1\n0001 PRINT\n0002 HALT\n"
    assert disassemble(compile_source("print 1;")) == expected


def test_disassembly_escapes_strings_and_bools() -> None:
    text = disassemble(compile_source('print "a\\"b"; print true;'))
    assert '; "a\\"b"' in text
    assert "; true" in text


def test_opcode_table_has_21_entries() -> None:
    assert len(OPCODES) == 21
    assert OPCODE_NUMBERS["CONST"] == 1
    assert OPCODE_NUMBERS["HALT"] == 21


def test_instr_is_frozen() -> None:
    instr = Instr("PRINT", None)
    with pytest.raises(dataclasses.FrozenInstanceError):
        instr.op = "POP"  # type: ignore[misc]


def test_cli_run_prints_expected(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    src = tmp_path / "t.mv"
    src.write_text("let x = 5; print x; print 8 / 2;\n", encoding="utf-8")
    assert main(["run", str(src)]) == 0
    assert capsys.readouterr().out == "5\n4.0\n"


def test_cli_run_failure_prints_nothing_to_stdout(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    src = tmp_path / "bad.mv"
    src.write_text('print "partial"; print 1 / 0;', encoding="utf-8")
    assert main(["run", str(src)]) == 3
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err != ""


def test_cli_build_then_exec_and_disasm(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    src = tmp_path / "p.mv"
    out = tmp_path / "p.bin"
    src.write_text("print 1 + 2;", encoding="utf-8")
    assert main(["build", str(src), str(out), "--optimize"]) == 0
    assert main(["exec", str(out)]) == 0
    assert capsys.readouterr().out.endswith("3\n")
    assert main(["disasm", str(out)]) == 0
    assert "HALT" in capsys.readouterr().out


def test_cli_unknown_command_is_usage_error(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["frobnicate"]) == 2


def test_cli_missing_argument_is_usage_error() -> None:
    assert main(["run"]) == 2


def test_cli_missing_file_is_usage_error(tmp_path: Path) -> None:
    assert main(["run", str(tmp_path / "nope.mv")]) == 2


def test_cli_bad_step_limit_is_usage_error(tmp_path: Path) -> None:
    src = tmp_path / "s.mv"
    src.write_text("print 1;", encoding="utf-8")
    assert main(["run", str(src), "--step-limit", "0"]) == 2
    assert main(["run", str(src), "--step-limit", "abc"]) == 2


def test_cli_step_limit_exceeded_is_exit_3(tmp_path: Path) -> None:
    src = tmp_path / "loop.mv"
    src.write_text("while (true) { }", encoding="utf-8")
    assert main(["run", str(src), "--step-limit", "50"]) == 3


def test_cli_exec_rejects_corrupt_binary(tmp_path: Path) -> None:
    binary = tmp_path / "bad.bin"
    binary.write_bytes(b"not a microvm binary")
    assert main(["exec", str(binary)]) == 3
