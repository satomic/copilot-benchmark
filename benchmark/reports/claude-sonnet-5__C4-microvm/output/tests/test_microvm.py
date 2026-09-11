"""Tests for the microvm package."""

import struct

import pytest

import microvm as m
from microvm.errors import StepLimitError


def run_src(src: str, *, optimize: bool = False, step_limit: int = 100_000) -> list[str]:
    program = m.compile_source(src, optimize=optimize)
    return m.execute(program, step_limit=step_limit)


# ---------------------------------------------------------------------------
# Package surface
# ---------------------------------------------------------------------------

def test_all_exports_count() -> None:
    assert len(m.__all__) == 19


def test_opcodes_exact() -> None:
    assert m.OPCODES == (
        "CONST", "LOAD", "STORE", "ADD", "SUB", "MUL", "DIV", "MOD", "NEG", "NOT",
        "EQ", "NE", "LT", "LE", "GT", "GE", "JUMP", "JUMP_IF_FALSE", "PRINT", "POP", "HALT",
    )
    assert m.OPCODE_NUMBERS["CONST"] == 1
    assert m.OPCODE_NUMBERS["HALT"] == 21


# ---------------------------------------------------------------------------
# Lexer
# ---------------------------------------------------------------------------

def test_lex_keywords_case_sensitive() -> None:
    toks = m.tokenize("IF if")
    assert toks[0].kind == "IDENT"
    assert toks[1].kind == "KEYWORD"


def test_lex_float_basic() -> None:
    toks = m.tokenize("1.5e3 2.0E-2")
    assert [(t.kind, t.value) for t in toks] == [("FLOAT", 1500.0), ("FLOAT", 0.02)]


def test_lex_bad_float_trailing_dot() -> None:
    with pytest.raises(m.LexError):
        m.tokenize("1.")


def test_lex_bad_float_leading_dot() -> None:
    with pytest.raises(m.LexError):
        m.tokenize(".5")


def test_lex_string_escapes() -> None:
    tok = m.tokenize('"a\\nb\\t\\"\\\\c"')[0]
    assert tok.value == "a\nb\t\"\\c"


def test_lex_unterminated_string() -> None:
    with pytest.raises(m.LexError):
        m.tokenize('"abc')


def test_lex_string_literal_newline() -> None:
    with pytest.raises(m.LexError):
        m.tokenize('"abc\ndef"')


def test_lex_bad_escape() -> None:
    with pytest.raises(m.LexError):
        m.tokenize('"a\\qb"')


def test_lex_longest_match_operators() -> None:
    toks = m.tokenize("== = != <= < >= >")
    assert [t.text for t in toks] == ["==", "=", "!=", "<=", "<", ">=", ">"]


def test_lex_comment_to_end_of_line() -> None:
    toks = m.tokenize("1 // comment\n2")
    assert [t.value for t in toks] == [1, 2]


def test_lex_unexpected_character() -> None:
    with pytest.raises(m.LexError) as exc:
        m.tokenize("1 @ 2")
    assert exc.value.offset == 2


def test_lex_identifier_with_underscore_digits() -> None:
    tok = m.tokenize("_abc123")[0]
    assert tok.kind == "IDENT"
    assert tok.text == "_abc123"


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

def test_parse_comparison_not_associative() -> None:
    with pytest.raises(m.ParseError):
        m.parse("print 1 < 2 < 3;")


def test_parse_if_else_if_chain() -> None:
    m.parse('if (1 > 0) { print "a"; } else if (1 > 1) { print "b"; } else { print "c"; }')


def test_parse_missing_semicolon() -> None:
    with pytest.raises(m.ParseError):
        m.parse("let x = 1")


def test_parse_lexerror_propagates() -> None:
    with pytest.raises(m.LexError):
        m.parse("let x = 1.;")


def test_parse_error_offset_attribute() -> None:
    with pytest.raises(m.ParseError) as exc:
        m.parse("let = 1;")
    assert isinstance(exc.value.offset, int)


# ---------------------------------------------------------------------------
# Section 1 semantics
# ---------------------------------------------------------------------------

def test_int_arithmetic() -> None:
    assert run_src("print 1 + 2 * 3;") == ["7"]


def test_float_promotion() -> None:
    assert run_src("print 1 + 2.0;") == ["3.0"]


def test_string_concatenation() -> None:
    assert run_src('print "a" + "b";') == ["ab"]


def test_string_plus_int_error() -> None:
    with pytest.raises(m.VMRuntimeError):
        run_src('print "a" + 1;')


def test_division_always_float() -> None:
    assert run_src("print 7 / 2;") == ["3.5"]
    assert run_src("print 8 / 2;") == ["4.0"]


def test_modulo_sign_rule() -> None:
    assert run_src("print -7 % 3;") == ["2"]


def test_division_by_zero() -> None:
    with pytest.raises(m.VMRuntimeError):
        run_src("print 1 / 0;")


def test_modulo_by_zero() -> None:
    with pytest.raises(m.VMRuntimeError):
        run_src("print 1 % 0;")


def test_modulo_requires_ints() -> None:
    with pytest.raises(m.VMRuntimeError):
        run_src("print 1.5 % 1;")


def test_unary_neg_requires_number() -> None:
    with pytest.raises(m.VMRuntimeError):
        run_src('print -"a";')


def test_unary_neg_number() -> None:
    assert run_src("print -(1 + 2);") == ["-3"]


def test_eq_bool_differs_from_int() -> None:
    assert run_src("print true == 1;") == ["false"]


def test_eq_int_float_numeric() -> None:
    assert run_src("print 1 == 1.0;") == ["true"]


def test_ne_never_raises_for_mismatched_types() -> None:
    assert run_src('print 1 != "1";') == ["true"]


def test_order_numbers_cross_type() -> None:
    assert run_src("print 1 < 1.5;") == ["true"]


def test_order_strings_by_codepoint() -> None:
    assert run_src('print "a" < "b";') == ["true"]


def test_order_bool_raises() -> None:
    with pytest.raises(m.VMRuntimeError):
        run_src("print true < false;")


def test_order_mixed_types_raises() -> None:
    with pytest.raises(m.VMRuntimeError):
        run_src('print 1 < "1";')


def test_and_short_circuits_false() -> None:
    assert run_src("print false and (1 / 0 == 0);") == ["false"]


def test_or_short_circuits_true() -> None:
    assert run_src("print true or (1 / 0 == 0);") == ["true"]


def test_and_requires_bool_right_operand() -> None:
    with pytest.raises(m.VMRuntimeError):
        run_src("print true and 5;")


def test_or_requires_bool_left_operand() -> None:
    with pytest.raises(m.VMRuntimeError):
        run_src("print 5 or true;")


def test_not_requires_bool() -> None:
    with pytest.raises(m.VMRuntimeError):
        run_src("print not 1;")


def test_not_basic() -> None:
    assert run_src("print not true;") == ["false"]


def test_if_condition_must_be_bool() -> None:
    with pytest.raises(m.VMRuntimeError):
        run_src("if (1) { print 1; }")


def test_while_condition_must_be_bool() -> None:
    with pytest.raises(m.VMRuntimeError):
        run_src("while (1) { print 1; }")


def test_print_rendering_all_types() -> None:
    src = 'let a = 1; let b = 2.0; let c = true; let d = "hi"; print a; print b; print c; print d;'
    assert run_src(src) == ["1", "2.0", "true", "hi"]


# ---------------------------------------------------------------------------
# Declarations / scoping
# ---------------------------------------------------------------------------

def test_no_block_scope() -> None:
    assert run_src("let x = 1; { let y = 2; x = y; } print x;") == ["2"]


def test_duplicate_let_is_compile_error() -> None:
    with pytest.raises(m.CompileError):
        m.compile_source("let x = 1; let x = 2;")


def test_assign_undeclared_is_compile_error() -> None:
    with pytest.raises(m.CompileError):
        m.compile_source("x = 1;")


def test_read_undeclared_is_compile_error() -> None:
    with pytest.raises(m.CompileError):
        m.compile_source("print x;")


def test_let_in_dead_branch_declares_but_never_assigns() -> None:
    program = m.compile_source("if (false) { let x = 1; } print 2;")
    assert "x" in program.names


def test_read_never_assigned_is_runtime_error() -> None:
    program = m.compile_source("let x; ".replace("let x; ", "if (false) { let x = 1; } print x;"))
    with pytest.raises(m.VMRuntimeError):
        m.execute(program)


def test_while_loop_runs() -> None:
    assert run_src("let x = 3; while (x > 0) { print x; x = x - 1; }") == ["3", "2", "1"]


# ---------------------------------------------------------------------------
# Compiler / bytecode shape
# ---------------------------------------------------------------------------

def test_print_literal_exactly_three_instructions() -> None:
    program = m.compile_source("print 1;")
    assert len(program.instructions) == 3


def test_halt_appears_exactly_once_at_end() -> None:
    program = m.compile_source('let x = 1; if (x == 1) { print "y"; }')
    halts = [i for i in program.instructions if i.op == "HALT"]
    assert len(halts) == 1
    assert program.instructions[-1].op == "HALT"


def test_constant_pool_dedup_by_type() -> None:
    program = m.compile_source("print 1; print 1; print 1.0; print true;")
    # exactly three distinct constants: int 1, float 1.0, bool true (1 deduped)
    assert len(program.constants) == 3
    kinds = [(type(c), c) for c in program.constants]
    assert (int, 1) in kinds
    assert (float, 1.0) in kinds
    assert (bool, True) in kinds


# ---------------------------------------------------------------------------
# Optimizer
# ---------------------------------------------------------------------------

def test_fold_constant_arithmetic() -> None:
    program = m.compile_source("print 1 + 2 * 3;", optimize=True)
    assert len(program.instructions) == 3


def test_fold_does_not_hide_division_by_zero() -> None:
    program = m.compile_source("print 1 / 0;", optimize=True)
    with pytest.raises(m.VMRuntimeError):
        m.execute(program)


def test_fold_does_not_hide_type_error_in_and() -> None:
    program = m.compile_source("let y = true and 5; print y;", optimize=True)
    with pytest.raises(m.VMRuntimeError):
        m.execute(program)


def test_fold_false_and_x_short_circuits_at_compile_time() -> None:
    program = m.compile_source("print false and (1 / 0 == 0);", optimize=True)
    assert m.execute(program) == ["false"]


def test_fold_true_or_x_short_circuits_at_compile_time() -> None:
    program = m.compile_source("print true or (1 / 0 == 0);", optimize=True)
    assert m.execute(program) == ["true"]


def test_fold_string_concat_not_folded_with_int() -> None:
    node = m.parse('print "a" + 1;')
    folded = m.fold_constants(node)
    assert folded is not None  # folding should not raise


def test_optimize_matches_unoptimized_behaviour() -> None:
    src = "let x = 2 + 3 * 4; print x; print x > 10;"
    assert run_src(src, optimize=False) == run_src(src, optimize=True)


# ---------------------------------------------------------------------------
# VM step limit
# ---------------------------------------------------------------------------

def test_infinite_loop_hits_step_limit() -> None:
    program = m.compile_source("while (true) {}")
    with pytest.raises(StepLimitError):
        m.execute(program, step_limit=1000)


def test_step_limit_must_be_positive_int() -> None:
    program = m.compile_source("print 1;")
    with pytest.raises(ValueError):
        m.execute(program, step_limit=0)


def test_step_limit_rejects_bool() -> None:
    program = m.compile_source("print 1;")
    with pytest.raises(ValueError):
        m.execute(program, step_limit=True)


# ---------------------------------------------------------------------------
# Serializer
# ---------------------------------------------------------------------------

def test_serializer_round_trip() -> None:
    program = m.compile_source('let x = 5; print x; print "hi"; print 2.5; print true;')
    data = m.dumps(program)
    program2 = m.loads(data)
    assert m.execute(program2) == m.execute(program)


def test_serializer_deterministic() -> None:
    program = m.compile_source("print 1 + 2;")
    assert m.dumps(program) == m.dumps(program)


def test_serializer_bad_magic() -> None:
    program = m.compile_source("print 1;")
    data = bytearray(m.dumps(program))
    data[0:4] = b"XXXX"
    with pytest.raises(m.SerializationError):
        m.loads(bytes(data))


def test_serializer_truncated() -> None:
    program = m.compile_source("print 1;")
    data = m.dumps(program)
    with pytest.raises(m.SerializationError):
        m.loads(data[:-10])


def test_serializer_checksum_mismatch() -> None:
    program = m.compile_source("print 1;")
    data = bytearray(m.dumps(program))
    data[-1] ^= 0xFF
    with pytest.raises(m.SerializationError):
        m.loads(bytes(data))


def test_serializer_trailing_bytes() -> None:
    program = m.compile_source("print 1;")
    data = m.dumps(program) + b"\x00\x00\x00\x00"
    with pytest.raises(m.SerializationError):
        m.loads(data)


def test_serializer_unsupported_version() -> None:
    program = m.compile_source("print 1;")
    data = bytearray(m.dumps(program))
    # version byte follows the 4-byte magic
    body_with_bad_version = bytes([data[4] + 1 if data[4] == 1 else 9]) + bytes(data[5:-4])
    import zlib
    new_body = body_with_bad_version
    new_checksum = zlib.crc32(new_body)
    new_data = data[0:4] + new_body + struct.pack(">I", new_checksum)
    with pytest.raises(m.SerializationError):
        m.loads(bytes(new_data))


def test_serializer_int_out_of_range() -> None:
    from microvm.compiler import Instr, Program
    program = Program([2 ** 63], [], [Instr("CONST", 0), Instr("PRINT", None), Instr("HALT", None)])
    with pytest.raises(m.SerializationError):
        m.dumps(program)


def test_serializer_unknown_opcode() -> None:
    program = m.compile_source("print 1;")
    data = bytearray(m.dumps(program))
    # Locate an instruction's opcode byte and corrupt it: find HALT's opcode byte (21)
    # by scanning from the end backward for the trailing 5-byte HALT record before checksum.
    idx = len(data) - 4 - 5
    original = data[idx]
    data[idx] = 200
    import zlib
    body = bytes(data[4:-4])
    new_checksum = zlib.crc32(body)
    data[-4:] = struct.pack(">I", new_checksum)
    with pytest.raises(m.SerializationError):
        m.loads(bytes(data))


def test_serializer_bool_payload_invalid() -> None:
    from microvm.compiler import Instr, Program
    program = Program([True], [], [Instr("CONST", 0), Instr("PRINT", None), Instr("HALT", None)])
    data = bytearray(m.dumps(program))
    # find the bool tag (0x04) followed by payload byte; set payload to 2
    tag_pos = data.index(0x04, 5)
    data[tag_pos + 1] = 2
    import zlib
    body = bytes(data[4:-4])
    new_checksum = zlib.crc32(body)
    data[-4:] = struct.pack(">I", new_checksum)
    with pytest.raises(m.SerializationError):
        m.loads(bytes(data))


# ---------------------------------------------------------------------------
# Disassembler
# ---------------------------------------------------------------------------

def test_disassemble_exact_output() -> None:
    program = m.compile_source("print 1;")
    assert m.disassemble(program) == "0000 CONST 0  ; 1\n0001 PRINT\n0002 HALT\n"


def test_disassemble_string_escaping() -> None:
    program = m.compile_source('print "a\\nb\\"c";')
    text = m.disassemble(program)
    assert '"a\\nb\\"c"' in text


def test_disassemble_jump_instructions_present() -> None:
    program = m.compile_source("let x = 1; while (x > 0) { x = x - 1; }")
    text = m.disassemble(program)
    assert "JUMP" in text


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def test_cli_run_success(tmp_path, capsys) -> None:
    src_file = tmp_path / "t.mv"
    src_file.write_text("let x = 5; print x; print 8 / 2;")
    from microvm.__main__ import main
    code = main(["run", str(src_file)])
    captured = capsys.readouterr()
    assert code == 0
    assert captured.out == "5\n4.0\n"


def test_cli_build_exec_disasm(tmp_path, capsys) -> None:
    from microvm.__main__ import main
    src_file = tmp_path / "t.mv"
    out_file = tmp_path / "t.bin"
    src_file.write_text("print 1 + 2;")
    assert main(["build", str(src_file), str(out_file)]) == 0
    capsys.readouterr()
    assert main(["exec", str(out_file)]) == 0
    assert capsys.readouterr().out == "3\n"
    assert main(["disasm", str(out_file)]) == 0
    out = capsys.readouterr().out
    assert "CONST" in out and "HALT" in out


def test_cli_unreadable_file_exit_2(tmp_path) -> None:
    from microvm.__main__ import main
    missing = tmp_path / "missing.mv"
    code = main(["run", str(missing)])
    assert code == 2


def test_cli_bad_step_limit_exit_2(tmp_path) -> None:
    from microvm.__main__ import main
    src_file = tmp_path / "t.mv"
    src_file.write_text("print 1;")
    code = main(["run", str(src_file), "--step-limit", "-3"])
    assert code == 2


def test_cli_unknown_command_exit_2() -> None:
    from microvm.__main__ import main
    code = main(["bogus"])
    assert code == 2


def test_cli_runtime_error_exit_3_no_stdout(tmp_path, capsys) -> None:
    from microvm.__main__ import main
    src_file = tmp_path / "t.mv"
    src_file.write_text("print 1 / 0;")
    code = main(["run", str(src_file)])
    captured = capsys.readouterr()
    assert code == 3
    assert captured.out == ""


def test_cli_step_limit_error_no_partial_stdout(tmp_path, capsys) -> None:
    from microvm.__main__ import main
    src_file = tmp_path / "t.mv"
    src_file.write_text('print "before"; while (true) {}')
    code = main(["run", str(src_file), "--step-limit", "50"])
    captured = capsys.readouterr()
    assert code == 3
    assert captured.out == ""
