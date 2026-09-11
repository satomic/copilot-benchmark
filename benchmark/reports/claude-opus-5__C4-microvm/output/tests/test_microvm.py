"""Tests for the microvm package."""

from __future__ import annotations

import pathlib
import struct
import zlib

import pytest

import microvm
from microvm import (
    CompileError,
    LexError,
    OPCODE_NUMBERS,
    OPCODES,
    ParseError,
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


def run(src: str, *, optimize: bool = False, step_limit: int = 100_000) -> list[str]:
    """Compile and execute *src*, returning the printed lines."""
    return execute(compile_source(src, optimize=optimize), step_limit=step_limit)


# --------------------------------------------------------------------- lexer


def test_tokenize_integers_and_floats() -> None:
    tokens = tokenize("1 2.5 1.5e3 2.0E-2")
    assert [t.kind for t in tokens] == ["INT", "FLOAT", "FLOAT", "FLOAT"]
    assert [t.value for t in tokens] == [1, 2.5, 1500.0, 0.02]


def test_tokenize_rejects_trailing_dot_float() -> None:
    with pytest.raises(LexError) as info:
        tokenize("1.")
    assert info.value.offset == 1


def test_tokenize_rejects_leading_dot_float() -> None:
    with pytest.raises(LexError) as info:
        tokenize(".5")
    assert info.value.offset == 0


def test_tokenize_string_escapes() -> None:
    (token,) = tokenize(r'"a\n\t\"\\b"')
    assert token.kind == "STRING"
    assert token.value == 'a\n\t"\\b'
    assert token.text == token.value


def test_tokenize_rejects_bad_escape_and_unterminated() -> None:
    with pytest.raises(LexError):
        tokenize(r'"\q"')
    with pytest.raises(LexError):
        tokenize('"abc')
    with pytest.raises(LexError):
        tokenize('"ab\ncd"')


def test_tokenize_keywords_are_case_sensitive() -> None:
    tokens = tokenize("if IF let Let")
    assert [(t.kind, t.text) for t in tokens] == [
        ("KEYWORD", "if"),
        ("IDENT", "IF"),
        ("KEYWORD", "let"),
        ("IDENT", "Let"),
    ]


def test_tokenize_longest_operator_match_and_offsets() -> None:
    tokens = tokenize("a == b")
    assert [t.text for t in tokens] == ["a", "==", "b"]
    assert [t.offset for t in tokens] == [0, 2, 5]


def test_tokenize_comments_and_no_eof_token() -> None:
    assert tokenize("// nothing here") == []
    tokens = tokenize("1 // tail\n2")
    assert [t.value for t in tokens] == [1, 2]


def test_tokenize_unexpected_character() -> None:
    with pytest.raises(LexError) as info:
        tokenize("a $ b")
    assert info.value.offset == 2


# -------------------------------------------------------------------- parser


def test_parse_accepts_full_program() -> None:
    src = 'let x = 1; if (x > 0) { print "hi"; } else { while (x > 0) { x = x - 1; } }'
    assert parse(src) is not None


def test_parse_rejects_chained_comparison() -> None:
    with pytest.raises(ParseError):
        parse("print 1 < 2 < 3;")


def test_parse_rejects_missing_semicolon() -> None:
    with pytest.raises(ParseError):
        parse("print 1")


def test_parse_rejects_let_without_initializer() -> None:
    with pytest.raises(ParseError):
        parse("let x;")


def test_parse_lex_error_passes_through() -> None:
    with pytest.raises(LexError):
        parse("print .5;")


def test_parse_rejects_unclosed_block() -> None:
    with pytest.raises(ParseError):
        parse("{ print 1;")


def test_parse_else_if_chain() -> None:
    assert parse("if (true) { } else if (false) { } else { }") is not None


# ------------------------------------------------------------------ compiler


def test_print_literal_is_three_instructions() -> None:
    program = compile_source("print 1;")
    assert [(i.op, i.arg) for i in program.instructions] == [
        ("CONST", 0),
        ("PRINT", None),
        ("HALT", None),
    ]


def test_constant_pool_dedup_by_type_and_value() -> None:
    program = compile_source("print 1; print 1; print 1.0; print true;")
    assert program.constants == [1, 1.0, True]
    assert [type(c).__name__ for c in program.constants] == ["int", "float", "bool"]


def test_names_follow_declaration_order() -> None:
    program = compile_source("let b = 1; let a = 2; { let c = 3; }")
    assert program.names == ["b", "a", "c"]


def test_duplicate_let_is_compile_error() -> None:
    with pytest.raises(CompileError):
        compile_source("let x = 1; let x = 2;")


def test_assign_to_undeclared_is_compile_error() -> None:
    with pytest.raises(CompileError):
        compile_source("x = 1;")


def test_read_undeclared_is_compile_error() -> None:
    with pytest.raises(CompileError):
        compile_source("print zz;")


def test_exactly_one_halt_at_the_end() -> None:
    program = compile_source("let x = 0; while (x < 3) { if (true) { x = x + 1; } }")
    ops = [i.op for i in program.instructions]
    assert ops.count("HALT") == 1 and ops[-1] == "HALT"


def test_opcode_table_shape() -> None:
    assert len(OPCODES) == 21
    assert OPCODE_NUMBERS["CONST"] == 1 and OPCODE_NUMBERS["HALT"] == 21


def test_instr_arg_presence_matches_opcode() -> None:
    program = compile_source("let x = 1; print x; if (true) { print 2; }")
    with_arg = {"CONST", "LOAD", "STORE", "JUMP", "JUMP_IF_FALSE"}
    for instr in program.instructions:
        assert (instr.arg is not None) == (instr.op in with_arg)


def test_logical_operators_compile_to_jumps() -> None:
    program = compile_source("print true and false;")
    assert any(i.op == "JUMP_IF_FALSE" for i in program.instructions)


# ------------------------------------------------------------------ semantics


def test_int_and_float_arithmetic_types() -> None:
    assert run("print 1 + 2; print 1 + 2.0; print 2 * 3; print 5 - 1.5;") == [
        "3",
        "3.0",
        "6",
        "3.5",
    ]


def test_string_concatenation_and_mixed_addition_error() -> None:
    assert run('print "a" + "b";') == ["ab"]
    with pytest.raises(VMRuntimeError):
        run('print "a" + 1;')


def test_division_always_float() -> None:
    assert run("print 7 / 2; print 4 / 2;") == ["3.5", "2.0"]


def test_modulo_requires_ints_and_python_sign() -> None:
    assert run("print -7 % 3;") == ["2"]
    with pytest.raises(VMRuntimeError):
        run("print 7.0 % 2;")


def test_division_and_modulo_by_zero() -> None:
    with pytest.raises(VMRuntimeError):
        run("print 1 / 0;")
    with pytest.raises(VMRuntimeError):
        run("print 1 % 0;")


def test_unary_minus_requires_number() -> None:
    assert run("print -3; print -2.5;") == ["-3", "-2.5"]
    with pytest.raises(VMRuntimeError):
        run("print -true;")


def test_equality_rules() -> None:
    assert run("print 1 == 1.0; print true == false; print 1 != 2;") == [
        "true",
        "false",
        "true",
    ]


def test_bool_never_equals_int() -> None:
    assert run("print true == 1; print false != 0;") == ["false", "true"]


def test_equality_across_types_never_raises() -> None:
    assert run('print "a" == 1; print 1 != "a";') == ["false", "true"]


def test_ordering_numbers_and_strings() -> None:
    assert run('print 1 < 2.5; print "a" < "b"; print 3 >= 3;') == [
        "true",
        "true",
        "true",
    ]


def test_ordering_rejects_bool_and_mixtures() -> None:
    with pytest.raises(VMRuntimeError):
        run("print true < false;")
    with pytest.raises(VMRuntimeError):
        run('print 1 < "a";')


def test_logic_requires_bool_operands() -> None:
    with pytest.raises(VMRuntimeError):
        run("print true and 5;")
    with pytest.raises(VMRuntimeError):
        run("print 1 or true;")
    with pytest.raises(VMRuntimeError):
        run("print not 1;")


def test_short_circuit_skips_right_operand() -> None:
    assert run("print false and (1 / 0 == 0);") == ["false"]
    assert run("print true or (1 / 0 == 0);") == ["true"]


def test_short_circuit_still_checks_evaluated_operand() -> None:
    with pytest.raises(VMRuntimeError):
        run("print false or 5;")


def test_logic_truth_tables() -> None:
    assert run(
        "print true and true; print true and false; print false or true; print not false;"
    ) == ["true", "false", "true", "true"]


def test_conditions_must_be_bool() -> None:
    with pytest.raises(VMRuntimeError):
        run("if (1) { print 1; }")
    with pytest.raises(VMRuntimeError):
        run("while (1) { print 1; }")


def test_print_rendering() -> None:
    assert run('print 1; print 4 / 2; print true; print false; print "raw";') == [
        "1",
        "2.0",
        "true",
        "false",
        "raw",
    ]


def test_blocks_do_not_create_scope() -> None:
    assert run("{ let x = 1; } x = x + 1; print x;") == ["2"]


def test_never_assigned_variable_is_runtime_error() -> None:
    with pytest.raises(VMRuntimeError) as info:
        run("if (false) { let ghost = 1; } print ghost;")
    assert "ghost" in str(info.value)


def test_while_loop_and_assignment() -> None:
    assert run("let x = 3; while (x > 0) { print x; x = x - 1; }") == ["3", "2", "1"]


def test_if_else_if_else_chain() -> None:
    src = 'let x = 3; if (x > 5) { print "big"; } else if (x > 2) { print "mid"; } else { print "small"; }'
    assert run(src) == ["mid"]


# ------------------------------------------------------------------------ vm


def test_step_limit_stops_infinite_loop() -> None:
    with pytest.raises(StepLimitError):
        run("while (true) { }", step_limit=500)


def test_step_limit_error_is_runtime_error() -> None:
    assert issubclass(StepLimitError, VMRuntimeError)


def test_step_limit_boundary() -> None:
    program = compile_source("print 1;")
    assert execute(program, step_limit=3) == ["1"]
    with pytest.raises(StepLimitError):
        execute(program, step_limit=2)


def test_step_limit_must_be_positive_int() -> None:
    program = compile_source("print 1;")
    for bad in (0, -1, True, 1.5, "3"):
        with pytest.raises(ValueError):
            execute(program, step_limit=bad)  # type: ignore[arg-type]


# ----------------------------------------------------------------- optimizer


def test_folding_collapses_arithmetic() -> None:
    program = compile_source("print 1 + 2 * 3;", optimize=True)
    assert [(i.op, i.arg) for i in program.instructions] == [
        ("CONST", 0),
        ("PRINT", None),
        ("HALT", None),
    ]
    assert program.constants == [7]
    assert len(compile_source("print 1 + 2 * 3;").instructions) > 3


def test_folding_preserves_division_by_zero() -> None:
    program = compile_source("print 1 / 0;", optimize=True)
    assert len(program.instructions) > 3
    with pytest.raises(VMRuntimeError):
        execute(program)


def test_folding_preserves_type_errors() -> None:
    with pytest.raises(VMRuntimeError):
        run('print "a" + 1;', optimize=True)


def test_folding_keeps_strict_bool_check() -> None:
    with pytest.raises(VMRuntimeError):
        run("let y = true and 5; print y;", optimize=True)
    with pytest.raises(VMRuntimeError):
        run("let z = false or 5; print z;", optimize=True)


def test_folding_short_circuit_constants() -> None:
    program = compile_source("print false and (1 / 0 == 0);", optimize=True)
    assert [i.op for i in program.instructions] == ["CONST", "PRINT", "HALT"]
    assert execute(program) == ["false"]
    assert compile_source("print true or 5;", optimize=True).constants == [True]


def test_folding_bool_pairs_and_not() -> None:
    assert compile_source("print true and false;", optimize=True).constants == [False]
    assert compile_source("print not true;", optimize=True).constants == [False]


def test_folding_comparisons_and_unary() -> None:
    assert compile_source("print 1 < 2;", optimize=True).constants == [True]
    assert compile_source("print -(1 + 1);", optimize=True).constants == [-2]


def test_fold_constants_is_idempotent_on_folded_tree() -> None:
    tree = fold_constants(parse("print 1 + 2;"))
    assert fold_constants(tree) == tree


def test_optimized_and_unoptimized_agree() -> None:
    src = "let x = 2; print x * (3 + 4); print 10 % 4; print not (1 > 2);"
    assert run(src) == run(src, optimize=True)


# ---------------------------------------------------------------- serializer


def _body(data: bytes) -> bytes:
    return data[4:-4]


def _rebuild(body: bytes) -> bytes:
    return b"MVM1" + bytes(body) + struct.pack(">I", zlib.crc32(bytes(body)) & 0xFFFFFFFF)


def test_serializer_round_trip() -> None:
    src = 'let x = 1; let s = "hi\\n"; print x + 1; print s; print 2.5; print true;'
    program = compile_source(src)
    restored = loads(dumps(program))
    assert restored.names == program.names
    assert restored.constants == program.constants
    assert restored.instructions == program.instructions
    assert execute(restored) == execute(program)


def test_serializer_round_trip_with_jumps() -> None:
    src = "let x = 3; while (x > 0) { if (x == 2) { print x; } x = x - 1; }"
    program = compile_source(src)
    assert any(i.op in ("JUMP", "JUMP_IF_FALSE") for i in program.instructions)
    restored = loads(dumps(program))
    assert restored.instructions == program.instructions
    assert execute(restored) == execute(program) == ["2"]


def test_serializer_is_deterministic() -> None:
    program = compile_source("let x = 1; print x;")
    assert dumps(program) == dumps(program)


def test_serializer_header_layout() -> None:
    data = dumps(compile_source("print 1;"))
    assert data[:4] == b"MVM1" and data[4] == 1
    assert zlib.crc32(_body(data)) & 0xFFFFFFFF == struct.unpack(">I", data[-4:])[0]


def test_dumps_rejects_out_of_range_int() -> None:
    program = compile_source("print 1;")
    program.constants[0] = 2**63
    with pytest.raises(SerializationError):
        dumps(program)


def test_loads_rejects_bad_magic() -> None:
    data = bytearray(dumps(compile_source("print 1;")))
    data[0:4] = b"XXXX"
    with pytest.raises(SerializationError):
        loads(bytes(data))


def test_loads_rejects_bad_version() -> None:
    body = bytearray(_body(dumps(compile_source("print 1;"))))
    body[0] = 2
    with pytest.raises(SerializationError):
        loads(_rebuild(body))


def test_loads_rejects_checksum_mismatch() -> None:
    data = bytearray(dumps(compile_source("print 1;")))
    data[-1] ^= 0xFF
    with pytest.raises(SerializationError):
        loads(bytes(data))


def test_loads_rejects_truncation() -> None:
    data = dumps(compile_source("let x = 1; print x;"))
    with pytest.raises(SerializationError):
        loads(data[:6])
    truncated = bytearray(_body(data))[:-5]
    with pytest.raises(SerializationError):
        loads(_rebuild(truncated))


def test_loads_rejects_trailing_bytes() -> None:
    data = dumps(compile_source("print 1;"))
    with pytest.raises(SerializationError):
        loads(data + b"\x00")
    with pytest.raises(SerializationError):
        loads(_rebuild(bytearray(_body(data)) + b"\x00"))


def test_loads_rejects_unknown_constant_tag() -> None:
    body = bytearray(_body(dumps(compile_source("print 1;"))))
    assert body[5] == 0x01
    body[5] = 0x7F
    with pytest.raises(SerializationError):
        loads(_rebuild(body))


def test_loads_rejects_bad_bool_payload() -> None:
    body = bytearray(_body(dumps(compile_source("print true;"))))
    assert body[5] == 0x04 and body[6] == 0x01
    body[6] = 0x05
    with pytest.raises(SerializationError):
        loads(_rebuild(body))


def test_loads_rejects_unknown_opcode_number() -> None:
    body = bytearray(_body(dumps(compile_source("print 1;"))))
    body[-15] = 99
    with pytest.raises(SerializationError):
        loads(_rebuild(body))


def test_loads_rejects_argument_mismatch() -> None:
    body = bytearray(_body(dumps(compile_source("print 1;"))))
    body[-14:-10] = b"\xff\xff\xff\xff"  # CONST without an argument
    with pytest.raises(SerializationError):
        loads(_rebuild(body))
    body = bytearray(_body(dumps(compile_source("print 1;"))))
    body[-4:] = b"\x00\x00\x00\x00"  # HALT carrying an argument
    with pytest.raises(SerializationError):
        loads(_rebuild(body))


def test_loads_rejects_non_bytes() -> None:
    with pytest.raises(SerializationError):
        loads("MVM1")  # type: ignore[arg-type]


# -------------------------------------------------------------- disassembler


def test_disassemble_exact_listing() -> None:
    assert disassemble(compile_source("print 1;")) == (
        "0000 CONST 0  ; 1\n0001 PRINT\n0002 HALT\n"
    )


def test_disassemble_constant_rendering() -> None:
    listing = disassemble(compile_source('print 1.5; print true; print "a\\nb\\"c";'))
    assert "; 1.5" in listing
    assert "; true" in listing
    assert '; "a\\nb\\"c"' in listing


def test_disassemble_jump_arguments() -> None:
    listing = disassemble(compile_source("let x = 1; while (x > 0) { x = x - 1; }"))
    assert any(line.startswith("0000 CONST 0") for line in listing.splitlines())
    assert "JUMP " in listing and "JUMP_IF_FALSE " in listing


# ----------------------------------------------------------------------- CLI


def test_cli_run_prints_output(tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = tmp_path / "t.mv"
    path.write_text("let x = 5; print x; print 8 / 2;", encoding="utf-8")
    assert main(["run", str(path)]) == 0
    assert capsys.readouterr().out == "5\n4.0\n"


def test_cli_run_optimize_flag(tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = tmp_path / "t.mv"
    path.write_text("print 1 + 2 * 3;", encoding="utf-8")
    assert main(["run", str(path), "--optimize"]) == 0
    assert capsys.readouterr().out == "7\n"


def test_cli_build_exec_and_disasm(tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]) -> None:
    src = tmp_path / "t.mv"
    out = tmp_path / "t.mvb"
    src.write_text("print 1;", encoding="utf-8")
    assert main(["build", str(src), str(out)]) == 0
    assert capsys.readouterr().out == ""
    assert out.read_bytes()[:4] == b"MVM1"
    assert main(["exec", str(out)]) == 0
    assert capsys.readouterr().out == "1\n"
    assert main(["disasm", str(out)]) == 0
    assert capsys.readouterr().out == "0000 CONST 0  ; 1\n0001 PRINT\n0002 HALT\n"


def test_cli_missing_file_is_usage_error(tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["run", str(tmp_path / "nope.mv")]) == 2
    captured = capsys.readouterr()
    assert captured.out == "" and captured.err != ""


def test_cli_unknown_command_is_usage_error(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["frobnicate"]) == 2
    assert capsys.readouterr().out == ""


def test_cli_missing_argument_is_usage_error(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["run"]) == 2
    assert capsys.readouterr().out == ""


def test_cli_bad_step_limit_is_usage_error(tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = tmp_path / "t.mv"
    path.write_text("print 1;", encoding="utf-8")
    assert main(["run", str(path), "--step-limit", "0"]) == 2
    assert main(["run", str(path), "--step-limit", "-4"]) == 2
    assert main(["run", str(path), "--step-limit", "abc"]) == 2
    assert capsys.readouterr().out == ""


def test_cli_compile_error_exit_code(tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = tmp_path / "t.mv"
    path.write_text("print 1 < 2 < 3;", encoding="utf-8")
    assert main(["run", str(path)]) == 3
    captured = capsys.readouterr()
    assert captured.out == "" and "ParseError" in captured.err


def test_cli_runtime_error_writes_nothing_to_stdout(tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = tmp_path / "t.mv"
    path.write_text('print "before"; print 1 / 0;', encoding="utf-8")
    assert main(["run", str(path)]) == 3
    captured = capsys.readouterr()
    assert captured.out == "" and "VMRuntimeError" in captured.err


def test_cli_step_limit_exceeded_exit_code(tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = tmp_path / "t.mv"
    path.write_text("while (true) { }", encoding="utf-8")
    assert main(["run", str(path), "--step-limit", "50"]) == 3
    assert capsys.readouterr().out == ""


def test_cli_exec_rejects_corrupt_binary(tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = tmp_path / "bad.mvb"
    path.write_bytes(b"NOPE" + b"\x00" * 16)
    assert main(["exec", str(path)]) == 3
    assert capsys.readouterr().out == ""


# ------------------------------------------------------------------ package


def test_cli_handles_utf16_and_undecodable_sources(
    tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]
) -> None:
    utf16 = tmp_path / "u.mv"
    utf16.write_bytes("print 1;".encode("utf-16"))
    assert main(["run", str(utf16)]) == 0
    assert capsys.readouterr().out == "1\n"
    broken = tmp_path / "b.mv"
    broken.write_bytes(b"print \xff\xfe\xfa;")
    assert main(["run", str(broken)]) == 2
    assert capsys.readouterr().out == ""


def test_package_exports() -> None:
    assert len(microvm.__all__) == 19
    for name in microvm.__all__:
        assert hasattr(microvm, name)
