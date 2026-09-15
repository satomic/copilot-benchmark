"""End-to-end tests for the microvm toolchain."""

import struct
import zlib

import pytest

import microvm
from microvm import (
    OPCODE_NUMBERS,
    OPCODES,
    CompileError,
    LexError,
    MicroVMError,
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


def run(src: str, **kwargs: object) -> list[str]:
    return execute(compile_source(src, **kwargs))


# ---------------------------------------------------------------------------
# Lexer


def test_tokenize_literals() -> None:
    toks = tokenize('12 3.5 1.5e3 2.0E-2 "hi"')
    assert [t.kind for t in toks] == ["INT", "FLOAT", "FLOAT", "FLOAT", "STRING"]
    assert toks[0].value == 12
    assert toks[1].value == 3.5
    assert toks[2].value == 1500.0
    assert toks[3].value == 0.02
    assert toks[4].value == "hi" and toks[4].text == "hi"


def test_tokenize_keywords_case_sensitive() -> None:
    toks = tokenize("let IF if And and")
    assert toks[1].kind == "IDENT"  # IF is not a keyword
    assert toks[3].kind == "IDENT"
    assert toks[0].kind == toks[2].kind == toks[4].kind == "KEYWORD"


def test_tokenize_operators_longest_match() -> None:
    toks = tokenize("= == != < <= > >= + - * / % ( ) { } ;")
    assert [t.text for t in toks] == [
        "=", "==", "!=", "<", "<=", ">", ">=", "+", "-", "*", "/", "%",
        "(", ")", "{", "}", ";",
    ]
    assert all(t.kind == "OP" for t in toks)
    assert tokenize("a==b")[1].text == "=="  # '==' wins over '='
    assert tokenize("a= =b")[1].text == "="
    assert tokenize("a<=b")[1].text == "<="


def test_tokenize_bang_alone_is_error() -> None:
    with pytest.raises(LexError):
        tokenize("!")


def test_tokenize_comments_and_whitespace() -> None:
    toks = tokenize("1 // comment\n\t2")
    assert [t.value for t in toks] == [1, 2]


def test_tokenize_offsets() -> None:
    toks = tokenize("  abc 1.0")
    assert toks[0].offset == 2 and toks[1].offset == 6


def test_string_escapes() -> None:
    (tok,) = tokenize(r'"a\nb\tc\"d\\e"')
    assert tok.value == 'a\nb\tc"d\\e'


def test_lex_error_bad_escape() -> None:
    with pytest.raises(LexError) as exc:
        tokenize(r'"a\q"')
    assert exc.value.offset == 2


def test_lex_error_unterminated_string() -> None:
    with pytest.raises(LexError):
        tokenize('"abc')


def test_lex_error_newline_in_string() -> None:
    with pytest.raises(LexError):
        tokenize('"ab\ncd"')


def test_lex_error_trailing_dot_and_leading_dot() -> None:
    with pytest.raises(LexError):
        tokenize("1.")
    with pytest.raises(LexError):
        tokenize(".5")


def test_lex_error_offset_is_zero_based() -> None:
    with pytest.raises(LexError) as exc:
        tokenize("ok $")
    assert exc.value.offset == 3


def test_no_eof_token_emitted() -> None:
    assert len(tokenize("1")) == 1
    assert tokenize("") == []


# ---------------------------------------------------------------------------
# Parser


def test_parse_ok_returns_ast() -> None:
    assert parse("let x = 1;") is not None


def test_parse_error_missing_semicolon() -> None:
    with pytest.raises(ParseError) as exc:
        parse("let x = 1")
    assert isinstance(exc.value.offset, int) and exc.value.offset >= 0


def test_parse_error_comparison_not_associative() -> None:
    with pytest.raises(ParseError):
        parse("print 1 < 2 < 3;")


def test_parse_error_unexpected_token_offset() -> None:
    with pytest.raises(ParseError) as exc:
        parse("print ;")
    assert exc.value.offset == 6


def test_lex_error_passes_through_parse() -> None:
    with pytest.raises(LexError):
        parse("print @")


def test_parse_else_if_chain_ok() -> None:
    assert parse("if (true) {} else if (false) {} else {}") is not None


# ---------------------------------------------------------------------------
# Compiler


def test_compile_print_literal_exactly_three_instructions() -> None:
    prog = compile_source("print 1;")
    assert [i.op for i in prog.instructions] == ["CONST", "PRINT", "HALT"]


def test_constant_pool_dedup_int_float_bool() -> None:
    prog = compile_source("print 1; print 1; print 1.0; print true; print 1;")
    assert prog.constants == [1, 1.0, True]
    assert type(prog.constants[0]) is int
    assert type(prog.constants[1]) is float
    assert type(prog.constants[2]) is bool


def test_halt_exactly_once_at_end() -> None:
    prog = compile_source("let x = 1; while (x > 0) { x = x - 1; } print x;")
    ops = [i.op for i in prog.instructions]
    assert ops[-1] == "HALT" and ops.count("HALT") == 1


def test_compile_error_redeclaration() -> None:
    with pytest.raises(CompileError):
        compile_source("let x = 1; let x = 2;")


def test_compile_error_undeclared_read() -> None:
    with pytest.raises(CompileError):
        compile_source("print y;")


def test_compile_error_undeclared_assign() -> None:
    with pytest.raises(CompileError):
        compile_source("y = 3;")


def test_let_in_block_declares_globally() -> None:
    prog = compile_source("if (true) { let q = 1; } print q;")
    assert prog.names == ["q"]
    assert run("if (true) { let q = 7; } print q;") == ["7"]


def test_names_declaration_order() -> None:
    prog = compile_source("let b = 1; let a = 2; if (true) { let c = 3; }")
    assert prog.names == ["b", "a", "c"]


def test_opcodes_numbering() -> None:
    assert len(OPCODES) == 21
    assert OPCODE_NUMBERS == {name: i + 1 for i, name in enumerate(OPCODES)}
    assert OPCODE_NUMBERS["CONST"] == 1 and OPCODE_NUMBERS["HALT"] == 21


# ---------------------------------------------------------------------------
# VM semantics (section 1)


def test_int_arithmetic_yields_int() -> None:
    assert run("print 7 + 2; print 7 - 2; print 7 * 2;") == ["9", "5", "14"]


def test_float_operand_yields_float() -> None:
    assert run("print 1 + 2.0; print 2.5 * 2;") == ["3.0", "5.0"]


def test_string_concat() -> None:
    assert run('print "ab" + "cd";') == ["abcd"]


def test_string_plus_int_error() -> None:
    with pytest.raises(VMRuntimeError):
        run('print "a" + 1;')


def test_div_always_float() -> None:
    assert run("print 7 / 2; print 8 / 2;") == ["3.5", "4.0"]


def test_mod_sign_rule() -> None:
    assert run("print -7 % 3; print 7 % -3;") == ["2", "-2"]


def test_mod_requires_ints() -> None:
    with pytest.raises(VMRuntimeError):
        run("print 7.0 % 3;")


def test_division_by_zero_error() -> None:
    with pytest.raises(VMRuntimeError):
        run("print 1 / 0;")


def test_modulo_by_zero_error() -> None:
    with pytest.raises(VMRuntimeError):
        run("print 1 % 0;")


def test_unary_neg() -> None:
    assert run("print -5; print -2.5; print --3;") == ["-5", "-2.5", "3"]


def test_unary_neg_requires_number() -> None:
    with pytest.raises(VMRuntimeError):
        run('print -"x";')


def test_eq_never_raises_mixed_types() -> None:
    assert run('print 1 == "a"; print 1 != "a";') == ["false", "true"]


def test_eq_bool_differs_from_int() -> None:
    assert run("print true == 1; print false == 0;") == ["false", "false"]


def test_eq_int_float_numeric() -> None:
    assert run("print 1 == 1.0; print 1 != 1.0;") == ["true", "false"]


def test_relational_cross_type_numbers() -> None:
    assert run("print 1 < 1.5; print 2.0 >= 2;") == ["true", "true"]


def test_relational_strings_by_codepoint() -> None:
    assert run('print "abc" < "abd"; print "b" >= "B";') == ["true", "true"]


def test_relational_bool_error() -> None:
    with pytest.raises(VMRuntimeError):
        run("print true < false;")


def test_relational_mixed_string_number_error() -> None:
    with pytest.raises(VMRuntimeError):
        run('print "a" > 1;')


def test_and_short_circuits_right_side() -> None:
    assert run("print false and (1 / 0 == 0);") == ["false"]


def test_or_short_circuits_right_side() -> None:
    assert run("print true or (1 / 0 == 0);") == ["true"]


def test_and_evaluates_right_when_left_true() -> None:
    assert run("print true and true; print true and false;") == ["true", "false"]


def test_or_evaluates_right_when_left_false() -> None:
    assert run("print false or true; print false or false;") == ["true", "false"]


def test_and_right_operand_type_checked() -> None:
    with pytest.raises(VMRuntimeError):
        run("print true and 5;")


def test_or_right_operand_type_checked() -> None:
    with pytest.raises(VMRuntimeError):
        run('print false or "x";')


def test_and_left_operand_type_checked() -> None:
    with pytest.raises(VMRuntimeError):
        run("print 5 and true;")


def test_not_requires_bool() -> None:
    assert run("print not false;") == ["true"]
    with pytest.raises(VMRuntimeError):
        run("print not 0;")


def test_if_condition_must_be_bool() -> None:
    with pytest.raises(VMRuntimeError):
        run("if (1) { print 1; }")


def test_while_condition_must_be_bool() -> None:
    with pytest.raises(VMRuntimeError):
        run('while ("x") { }')


def test_print_rendering() -> None:
    out = run('print 1; print 4 / 2; print true; print false; print "raw";')
    assert out == ["1", "2.0", "true", "false", "raw"]


def test_never_assigned_variable_error() -> None:
    with pytest.raises(VMRuntimeError) as exc:
        run("if (false) { let z = 1; } print z;")
    assert "z" in str(exc.value)


def test_while_loop_counts_down() -> None:
    assert run("let x = 3; while (x > 0) { print x; x = x - 1; }") == ["3", "2", "1"]


def test_if_elif_else_chain() -> None:
    src = 'if (x > 5) { print "big"; } else if (x > 2) { print "mid"; } else { print "small"; }'
    assert run(f"let x = 9; {src}") == ["big"]
    assert run(f"let x = 3; {src}") == ["mid"]
    assert run(f"let x = 1; {src}") == ["small"]


def test_step_limit_terminates_infinite_loop() -> None:
    with pytest.raises(StepLimitError):
        execute(compile_source("while (true) { }"), step_limit=1000)


def test_step_limit_is_vm_runtime_error_subclass() -> None:
    with pytest.raises(VMRuntimeError):
        execute(compile_source("while (true) { }"), step_limit=10)


def test_step_limit_boundary() -> None:
    prog = compile_source("print 1;")  # exactly 3 instructions
    assert execute(prog, step_limit=3) == ["1"]
    with pytest.raises(StepLimitError):
        execute(prog, step_limit=2)


@pytest.mark.parametrize("bad", [0, -1, 2.5, True, "10"])
def test_step_limit_validation(bad: object) -> None:
    with pytest.raises(ValueError):
        execute(compile_source("print 1;"), step_limit=bad)


# ---------------------------------------------------------------------------
# Optimizer


def test_fold_arithmetic_to_three_instructions() -> None:
    prog = compile_source("print 1 + 2 * 3;", optimize=True)
    assert [i.op for i in prog.instructions] == ["CONST", "PRINT", "HALT"]
    assert prog.constants == [7]


def test_no_optimize_has_more_instructions() -> None:
    assert len(compile_source("print 1 + 2 * 3;").instructions) > 3


def test_fold_div_by_zero_stays_unfolded_and_raises() -> None:
    prog = compile_source("print 1 / 0;", optimize=True)
    assert len(prog.instructions) > 3
    with pytest.raises(VMRuntimeError):
        execute(prog)


def test_fold_string_plus_int_stays_unfolded_and_raises() -> None:
    with pytest.raises(VMRuntimeError):
        run('print "a" + 1;', optimize=True)


def test_fold_true_and_x_keeps_type_check() -> None:
    with pytest.raises(VMRuntimeError):
        run("let y = true and 5;", optimize=True)


def test_fold_false_or_x_keeps_type_check() -> None:
    with pytest.raises(VMRuntimeError):
        run("let y = false or 5;", optimize=True)


def test_fold_false_and_anything_is_safe() -> None:
    assert run("print false and (1 / 0 == 0);", optimize=True) == ["false"]


def test_fold_true_or_anything_is_safe() -> None:
    assert run("print true or (1 / 0 == 0);", optimize=True) == ["true"]


def test_fold_both_bool_operands() -> None:
    assert run("print true and false; print true or false;", optimize=True) == [
        "false",
        "true",
    ]


def test_fold_comparison_unary_and_not() -> None:
    out = run("print 1 + 1 == 2; print -3 + 1; print not false;", optimize=True)
    assert out == ["true", "-2", "true"]


def test_fold_constants_function_returns_ast() -> None:
    assert fold_constants(parse("print 1 + 2;")) is not None


def test_fold_does_not_change_undeclared_error() -> None:
    with pytest.raises(CompileError):
        compile_source("print 1 + q;", optimize=True)


# ---------------------------------------------------------------------------
# Serializer


def _sample_program() -> object:
    return compile_source(
        'let x = -42; let f = 2.5; let s = "hé\\n"; let b = true; '
        "while (x < 0) { x = x + 7; } print x; print f; print s; print b;"
    )


def test_serializer_round_trip() -> None:
    prog = _sample_program()
    back = loads(dumps(prog))
    assert back.constants == prog.constants
    assert back.names == prog.names
    assert back.instructions == prog.instructions


def test_dumps_deterministic() -> None:
    prog = _sample_program()
    assert dumps(prog) == dumps(prog)


def test_execute_after_round_trip_identical() -> None:
    prog = _sample_program()
    assert execute(loads(dumps(prog))) == execute(prog)


def test_loads_bad_magic() -> None:
    with pytest.raises(SerializationError):
        loads(b"XXXX" + dumps(compile_source("print 1;"))[4:])


def test_loads_bad_version() -> None:
    data = bytearray(dumps(compile_source("print 1;")))
    data[4] = 2
    crc = zlib.crc32(bytes(data[4:-4])) & 0xFFFFFFFF
    data[-4:] = struct.pack(">I", crc)
    with pytest.raises(SerializationError):
        loads(bytes(data))


def test_loads_checksum_mismatch() -> None:
    data = bytearray(dumps(compile_source("print 1;")))
    data[10] ^= 0xFF
    with pytest.raises(SerializationError):
        loads(bytes(data))


def test_loads_truncated() -> None:
    data = dumps(_sample_program())
    with pytest.raises(SerializationError):
        loads(data[:-6])
    with pytest.raises(SerializationError):
        loads(data[:6])


def test_loads_trailing_bytes() -> None:
    with pytest.raises(SerializationError):
        loads(dumps(compile_source("print 1;")) + b"junk")


def test_loads_unknown_constant_tag() -> None:
    data = bytearray(dumps(compile_source("print 1;")))
    # constants start after magic(4)+version(1)+namecount(2)+constcount(2)
    data[9] = 0x7F
    crc = zlib.crc32(bytes(data[4:-4])) & 0xFFFFFFFF
    data[-4:] = struct.pack(">I", crc)
    with pytest.raises(SerializationError):
        loads(bytes(data))


def test_loads_unknown_opcode() -> None:
    data = bytearray(dumps(compile_source("print 1;")))
    data[-9] = 99  # first byte of the last instruction record (HALT)
    crc = zlib.crc32(bytes(data[4:-4])) & 0xFFFFFFFF
    data[-4:] = struct.pack(">I", crc)
    with pytest.raises(SerializationError):
        loads(bytes(data))


def test_loads_no_arg_opcode_with_arg_rejected() -> None:
    data = bytearray(dumps(compile_source("print 1;")))
    data[-8:] = b"\x00\x00\x00\x01" + data[-4:]  # HALT arg != 0xFFFFFFFF
    crc = zlib.crc32(bytes(data[4:-4])) & 0xFFFFFFFF
    data[-4:] = struct.pack(">I", crc)
    with pytest.raises(SerializationError):
        loads(bytes(data))


def test_loads_arg_opcode_with_sentinel_rejected() -> None:
    data = bytearray(dumps(compile_source("print 1;")))
    # first instruction is CONST; its u32 arg sits right after the opcode byte
    data[23:27] = b"\xff\xff\xff\xff"
    crc = zlib.crc32(bytes(data[4:-4])) & 0xFFFFFFFF
    data[-4:] = struct.pack(">I", crc)
    with pytest.raises(SerializationError):
        loads(bytes(data))


def test_loads_bad_bool_payload() -> None:
    data = bytearray(dumps(compile_source("print true;")))
    assert data[9] == 0x04  # BOOL tag
    data[10] = 7
    crc = zlib.crc32(bytes(data[4:-4])) & 0xFFFFFFFF
    data[-4:] = struct.pack(">I", crc)
    with pytest.raises(SerializationError):
        loads(bytes(data))


def test_dumps_int_out_of_range() -> None:
    prog = compile_source("print 1;")
    prog.constants[0] = 2 ** 63
    with pytest.raises(SerializationError):
        dumps(prog)


# ---------------------------------------------------------------------------
# Disassembler


def test_disassemble_exact_example() -> None:
    expected = "0000 CONST 0  ; 1\n0001 PRINT\n0002 HALT\n"
    assert disassemble(compile_source("print 1;")) == expected


def test_disassemble_string_escapes() -> None:
    out = disassemble(compile_source(r'print "a\nb\t\\\"q";'))
    assert out == '0000 CONST 0  ; "a\\nb\\t\\\\\\"q"\n0001 PRINT\n0002 HALT\n'


def test_disassemble_bool_and_float_constants() -> None:
    out = disassemble(compile_source("print true; print 2.5;"))
    assert "; true" in out and "; 2.5" in out


def test_disassemble_jump_targets() -> None:
    out = disassemble(compile_source("while (false) { }"))
    assert "JUMP_IF_FALSE" in out and "JUMP" in out


# ---------------------------------------------------------------------------
# CLI


def _write(tmp_path: object, name: str, text: str) -> str:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return str(path)


def test_cli_run(tmp_path: object, capsys: object) -> None:
    src = _write(tmp_path, "a.mv", "let x = 5; print x; print 8 / 2;")
    assert main(["run", src]) == 0
    assert capsys.readouterr().out == "5\n4.0\n"


def test_cli_run_optimize(tmp_path: object, capsys: object) -> None:
    src = _write(tmp_path, "a.mv", "print 1 + 2 * 3;")
    assert main(["run", src, "--optimize"]) == 0
    assert capsys.readouterr().out == "7\n"


def test_cli_build_exec_disasm(tmp_path: object, capsys: object) -> None:
    src = _write(tmp_path, "a.mv", "print 42;")
    out = str(tmp_path / "a.mvb")
    assert main(["build", src, out]) == 0
    assert main(["exec", out]) == 0
    assert capsys.readouterr().out == "42\n"
    assert main(["disasm", out]) == 0
    assert capsys.readouterr().out == disassemble(compile_source("print 42;"))


def test_cli_unknown_command_exit_2(capsys: object) -> None:
    assert main(["bogus"]) == 2
    assert capsys.readouterr().out == ""


def test_cli_missing_argument_exit_2(capsys: object) -> None:
    assert main(["run"]) == 2
    assert capsys.readouterr().out == ""


def test_cli_unreadable_file_exit_2(tmp_path: object, capsys: object) -> None:
    assert main(["run", str(tmp_path / "nope.mv")]) == 2
    assert capsys.readouterr().out == ""


def test_cli_bad_step_limit_exit_2(tmp_path: object, capsys: object) -> None:
    src = _write(tmp_path, "a.mv", "print 1;")
    assert main(["run", src, "--step-limit", "0"]) == 2
    assert main(["run", src, "--step-limit", "abc"]) == 2
    assert capsys.readouterr().out == ""


def test_cli_microvm_error_exit_3(tmp_path: object, capsys: object) -> None:
    src = _write(tmp_path, "a.mv", "print 1 / 0;")
    assert main(["run", src]) == 3
    captured = capsys.readouterr()
    assert captured.out == "" and "error" in captured.err


def test_cli_no_stdout_on_midway_failure(tmp_path: object, capsys: object) -> None:
    src = _write(tmp_path, "a.mv", "print 1; print 2; print 1 / 0;")
    assert main(["run", src]) == 3
    assert capsys.readouterr().out == ""


def test_cli_step_limit_error_exit_3(tmp_path: object, capsys: object) -> None:
    src = _write(tmp_path, "a.mv", "while (true) { }")
    assert main(["run", src, "--step-limit", "50"]) == 3
    assert capsys.readouterr().out == ""


def test_cli_exec_corrupt_binary_exit_3(tmp_path: object, capsys: object) -> None:
    src = _write(tmp_path, "a.mv", "print 1;")
    out = str(tmp_path / "a.mvb")
    assert main(["build", src, out]) == 0
    data = bytearray((tmp_path / "a.mvb").read_bytes())
    data[12] ^= 0xFF
    (tmp_path / "a.mvb").write_bytes(bytes(data))
    assert main(["exec", out]) == 3
    assert capsys.readouterr().out == ""


# ---------------------------------------------------------------------------
# Errors & package surface


def test_error_hierarchy() -> None:
    assert issubclass(LexError, MicroVMError)
    assert issubclass(ParseError, MicroVMError)
    assert issubclass(CompileError, MicroVMError)
    assert issubclass(SerializationError, MicroVMError)
    assert issubclass(VMRuntimeError, MicroVMError)
    assert issubclass(StepLimitError, VMRuntimeError)


def test_all_exports() -> None:
    assert len(microvm.__all__) == 19
    for name in microvm.__all__:
        assert hasattr(microvm, name)
    assert "StepLimitError" not in microvm.__all__
