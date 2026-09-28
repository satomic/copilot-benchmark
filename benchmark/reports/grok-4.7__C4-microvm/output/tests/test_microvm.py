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
    MicroVMError,
    ParseError,
    Program,
    SerializationError,
    Token,
    VMRuntimeError,
    compile_source,
    disassemble,
    dumps,
    execute,
    loads,
    parse,
    tokenize,
)
from microvm.__main__ import main
from microvm.errors import StepLimitError

ROOT = Path(__file__).resolve().parents[1]


def _run(src: str, optimize: bool = False, step_limit: int = 100_000) -> list[str]:
    return execute(compile_source(src, optimize=optimize), step_limit=step_limit)


def _norm(text: str) -> str:
    return text.replace("\r\n", "\n")


def _rechecksum(body: bytes) -> bytes:
    crc = zlib.crc32(body) & 0xFFFFFFFF
    return b"MVM1" + body + crc.to_bytes(4, "big")


def test_tokenize_basics() -> None:
    tokens = tokenize("let x = 10;")
    assert [token.kind for token in tokens] == ["KEYWORD", "IDENT", "OP", "INT", "OP"]
    assert tokens[0] == Token("KEYWORD", "let", "let", 0)
    assert tokens[3].value == 10
    assert tokenize("") == []
    assert tokenize("   // only a comment\n") == []


def test_keywords_are_case_sensitive() -> None:
    tokens = tokenize("IF True letter or_ iff")
    assert [token.kind for token in tokens] == ["IDENT"] * 5
    assert tokenize("true false and or not").__len__() == 5
    assert all(token.kind == "KEYWORD" for token in tokenize("while if else print let"))


def test_floats_and_exponent_split() -> None:
    value = tokenize("1.5e3 2.0E-2 1.0e+10 00.50")
    assert value[0].value == 1500.0
    assert value[1].value == 0.02
    assert value[2].value == 1.0e10
    assert value[3].text == "00.50"
    split = tokenize("1e3 1.5e")
    assert [token.kind for token in split] == ["INT", "IDENT", "FLOAT", "IDENT"]


def test_invalid_numbers_are_lex_errors() -> None:
    with pytest.raises(LexError) as dotted:
        tokenize("1.")
    assert dotted.value.offset == 1
    with pytest.raises(LexError) as leading:
        tokenize(".5")
    assert leading.value.offset == 0
    with pytest.raises(LexError) as bang:
        tokenize("!")
    assert bang.value.offset == 0


def test_strings_and_escapes() -> None:
    token = tokenize(r'"a\n\t\"\\"')[0]
    assert token.kind == "STRING"
    assert token.text == "a\n\t\"\\"
    assert token.value == token.text
    assert tokenize('""')[0].value == ""
    assert tokenize('"//"')[0].value == "//"


def test_string_errors() -> None:
    with pytest.raises(LexError) as bad:
        tokenize(r'"\x"')
    assert bad.value.offset == 1
    with pytest.raises(LexError) as open_quote:
        parse('print "unterminated;')
    assert isinstance(open_quote.value, LexError)
    assert open_quote.value.offset == 6
    with pytest.raises(LexError):
        tokenize('"line\n"')


def test_comments_whitespace_and_longest_match() -> None:
    src = "let\tx // c\n= 1==2 != 3 <= 4 >= 5;"
    kinds = [(token.kind, token.text) for token in tokenize(src)]
    assert ("OP", "==") in kinds
    assert ("OP", "!=") in kinds
    assert ("OP", "<=") in kinds
    assert ("OP", ">=") in kinds
    assert ("OP", "=") in kinds


def test_parse_errors() -> None:
    with pytest.raises(ParseError) as chained:
        parse("print 1 < 2 < 3;")
    assert chained.value.offset > 0
    with pytest.raises(ParseError):
        parse("print 1")
    with pytest.raises(ParseError):
        parse("let x;")
    with pytest.raises(ParseError):
        parse("if true { print 1; }")
    with pytest.raises(ParseError):
        parse("else { print 1; }")
    with pytest.raises(ParseError):
        parse("print +1;")


def test_arithmetic_types() -> None:
    assert _run("print 1 + 2; print 5 - 2; print 3 * 4;") == ["3", "3", "12"]
    assert _run("print 1 + 2.0; print 2.5 * 2;") == ["3.0", "5.0"]
    assert _run('print "ab" + "cd";') == ["abcd"]
    with pytest.raises(VMRuntimeError):
        _run('print "a" + 1;')
    with pytest.raises(VMRuntimeError):
        _run("print true + 1;")
    with pytest.raises(VMRuntimeError):
        _run("print 1 - true;")


def test_division_and_modulo() -> None:
    assert _run("print 7 / 2; print 8 / 2; print 5 / 2.0;") == ["3.5", "4.0", "2.5"]
    assert _run("print -7 % 3; print 7 % -3; print -7 % -3;") == ["2", "-2", "-1"]
    with pytest.raises(VMRuntimeError):
        _run("print 1 / 0;")
    with pytest.raises(VMRuntimeError):
        _run("print 1.0 / 0.0;")
    with pytest.raises(VMRuntimeError):
        _run("print 1 % 0;")
    with pytest.raises(VMRuntimeError):
        _run("print 7.0 % 2;")


def test_unary_minus() -> None:
    assert _run("print -5; print -2.5; print --5; print -2 * 3; print 2 * -3;") == [
        "-5",
        "-2.5",
        "5",
        "-6",
        "-6",
    ]
    with pytest.raises(VMRuntimeError):
        _run("print -true;")
    with pytest.raises(VMRuntimeError):
        _run('print -"a";')


def test_equality_never_raises() -> None:
    src = """
    print true == 1;
    print true != 1;
    print 1 == 1.0;
    print 1 != 1.0;
    print true == true;
    print false == 0;
    print 1 == "1";
    print "a" != "b";
    """
    assert _run(src) == ["false", "true", "true", "false", "true", "false", "false", "true"]


def test_ordered_comparisons() -> None:
    src = """
    print 1 < 2;
    print 1 <= 1.0;
    print 2 > 1.5;
    print 2 >= 2;
    print "a" < "b";
    print "10" < "2";
    print "ab" >= "ab";
    """
    assert _run(src) == ["true", "true", "true", "true", "true", "true", "true"]
    for src in ("print true < false;", "print 1 < true;", 'print "a" < 1;', "print false >= 0;"):
        with pytest.raises(VMRuntimeError):
            _run(src)


def test_logic_short_circuit() -> None:
    assert _run("print false and (1 / 0 == 0);") == ["false"]
    assert _run("print true or (1 / 0 == 0);") == ["true"]
    assert _run("print true and false; print false or true; print not false;") == [
        "false",
        "true",
        "true",
    ]
    with pytest.raises(VMRuntimeError):
        _run("print true and 5;")
    with pytest.raises(VMRuntimeError):
        _run("print false or 5;")
    with pytest.raises(VMRuntimeError):
        _run("print 1 and true;")
    with pytest.raises(VMRuntimeError):
        _run("print true and (1 / 0 == 0);")


def test_uninitialized_right_side_is_skipped() -> None:
    src = "if (false) { let z = 1; } print false and (z == 1); print true or (z == 1);"
    assert _run(src) == ["false", "true"]
    with pytest.raises(VMRuntimeError) as caught:
        _run("if (false) { let z = 1; } print false or (z == 1);")
    assert "z" in str(caught.value)


def test_not_precedence() -> None:
    assert _run("print not 1 == 2; print not not true; print not false == true;") == [
        "true",
        "true",
        "true",
    ]
    assert _run("print true or false and false; print false and true or true;") == ["true", "true"]
    with pytest.raises(VMRuntimeError):
        _run("print not 5;")


def test_left_associativity_and_precedence() -> None:
    assert _run("print 10 - 3 - 2; print 1 + 2 * 3; print 20 / 2 / 2;") == ["5", "7", "5.0"]
    assert _run("print 10 % 4 % 3;") == ["2"]
    assert _run('print "a" + "b" + "c";') == ["abc"]


def test_if_else_and_while() -> None:
    src = """
    let x = 3;
    if (x > 5) { print "big"; } else if (x > 2) { print "mid"; } else { print "small"; }
    if (false) { print "no"; }
    while (x > 0) { print x; x = x - 1; }
    """
    assert _run(src) == ["mid", "3", "2", "1"]
    with pytest.raises(VMRuntimeError):
        _run("if (1) { print 1; }")
    with pytest.raises(VMRuntimeError):
        _run("while (1) { print 1; }")


def test_print_rendering() -> None:
    src = 'print true; print false; print 4 / 2; print "a\\nb"; print 0;'
    assert _run(src) == ["true", "false", "2.0", "a\nb", "0"]


def test_blocks_share_one_namespace() -> None:
    src = """
    let x = 1;
    { let y = 2; x = 3; }
    print x;
    print y;
    """
    assert _run(src) == ["3", "2"]


def test_duplicate_and_undeclared_are_compile_errors() -> None:
    with pytest.raises(CompileError):
        compile_source("let x = 1; let x = 2;")
    with pytest.raises(CompileError):
        compile_source("if (true) { let x = 1; } else { let x = 2; }")
    with pytest.raises(CompileError):
        compile_source("x = 1;")
    with pytest.raises(CompileError):
        compile_source("print missing;")


def test_uninitialized_variable_names_itself() -> None:
    src = "if (false) { let x = 1; } print x;"
    with pytest.raises(VMRuntimeError) as caught:
        _run(src)
    assert "x" in str(caught.value)
    with pytest.raises(VMRuntimeError) as forward:
        _run("let x = y; let y = 1;")
    assert "y" in str(forward.value)


def test_dead_branch_still_declares() -> None:
    program = compile_source("if (false) { let x = 1; } let y = 2;")
    assert program.names == ["x", "y"]
    assert _run("if (false) { let x = 1 / 0; } print 1;") == ["1"]


def test_constant_pool_dedup() -> None:
    program = compile_source("print 1; print 1; print 1.0; print true; print false;")
    assert program.constants[0] == 1 and type(program.constants[0]) is int
    assert program.constants[1] == 1.0 and type(program.constants[1]) is float
    assert program.constants[2] is True
    assert program.constants[3] is False
    assert program.constants.count(1) >= 1
    const_args = [instr.arg for instr in program.instructions if instr.op == "CONST"]
    assert const_args[:2] == [0, 0]


def test_negative_zero_pool_is_distinct() -> None:
    program = compile_source("print 0.0; print -0.0;", optimize=True)
    assert _run("print 0.0; print -0.0;", optimize=True) == ["0.0", "-0.0"]
    assert len(program.constants) == 2
    packed = [struct.pack(">d", value) for value in program.constants]
    assert packed[0] != packed[1]


def test_print_literal_is_three_instructions() -> None:
    program = compile_source("print 1;")
    assert [instr.op for instr in program.instructions] == ["CONST", "PRINT", "HALT"]
    assert len(program.instructions) == 3
    assert program.instructions[0].arg == 0
    assert program.instructions[1].arg is None


def test_halt_only_at_end_and_names_in_order() -> None:
    src = "let b = 1; if (false) { let c = b; } let a = 2; print a;"
    program = compile_source(src)
    assert program.names == ["b", "c", "a"]
    assert program.instructions[-1] == Instr("HALT", None)
    assert all(instr.op != "HALT" for instr in program.instructions[:-1])
    assert _run(src) == ["2"]


def test_fold_reduces_print_expression() -> None:
    folded = compile_source("print 1 + 2 * 3;", optimize=True)
    plain = compile_source("print 1 + 2 * 3;")
    assert [instr.op for instr in folded.instructions] == ["CONST", "PRINT", "HALT"]
    assert len(plain.instructions) > 3
    assert folded.constants == [7]
    assert _run("print 1 + 2 * 3;", optimize=True) == ["7"]


def test_fold_preserves_observable_results() -> None:
    src = """
    let x = 1 + 2 * 3;
    let y = x - 4;
    if (y > 0 and y < 10) { print y; } else { print "no"; }
    print 8 / 2;
    print -7 % 3;
    print "a" + "b";
    print 1 == 1.0;
    print true == 1;
    print not false;
    """
    assert _run(src) == _run(src, optimize=True)
    assert _run(src) == ["3", "4.0", "2", "ab", "true", "false", "true"]


def test_fold_keeps_failing_operations() -> None:
    divided = compile_source("print 1 / 0;", optimize=True)
    assert any(instr.op == "DIV" for instr in divided.instructions)
    with pytest.raises(VMRuntimeError):
        _run("print 1 / 0;", optimize=True)
    with pytest.raises(VMRuntimeError):
        _run("let y = true and 5; print y;", optimize=True)
    with pytest.raises(VMRuntimeError):
        _run("let y = false or 5;", optimize=True)
    mixed = compile_source('print "a" + 1;', optimize=True)
    assert any(instr.op == "ADD" for instr in mixed.instructions)


def test_fold_short_circuit_constants() -> None:
    assert _run("print false and (1 / 0 == 0);", optimize=True) == ["false"]
    assert _run("print true or (1 / 0 == 0);", optimize=True) == ["true"]
    folded = compile_source("print false and (1 / 0 == 0);", optimize=True)
    assert [instr.op for instr in folded.instructions] == ["CONST", "PRINT", "HALT"]
    assert _run("print true and false;", optimize=True) == ["false"]
    assert _run("let y = 1; print true and (y == 1);", optimize=True) == ["true"]


def test_disassemble_exact_print_one() -> None:
    text = disassemble(compile_source("print 1;"))
    assert text == "0000 CONST 0  ; 1\n0001 PRINT\n0002 HALT\n"


def test_disassemble_renders_constants() -> None:
    src = 'print "a\\nb\\t\\"\\\\"; print true; print 1.5;'
    text = disassemble(compile_source(src))
    assert '  ; "a\\nb\\t\\"\\\\"' in text
    assert "  ; true" in text
    assert "  ; 1.5" in text
    assert text.endswith("\n")


def test_serializer_round_trip_behavior() -> None:
    src = """
    let n = 3;
    while (n > 0) { print n; n = n - 1; }
    print 1 == 1.0;
    print true;
    print "héllo\\t";
    print -0.0;
    print -7 % 3;
    """
    program = compile_source(src)
    restored = loads(dumps(program))
    assert restored.names == program.names
    assert restored.instructions == program.instructions
    assert execute(restored) == execute(program)
    assert any(value is True for value in restored.constants)


def test_serializer_is_deterministic_and_layout() -> None:
    program = compile_source("print 1;")
    assert dumps(program) == dumps(program)
    data = dumps(program)
    assert data[:4] == b"MVM1"
    assert data[4] == 1
    assert data[5:7] == b"\x00\x00"
    assert data[7:9] == b"\x00\x01"
    assert data[9] == 0x01
    assert int.from_bytes(data[10:18], "big", signed=True) == 1
    body = data[4:-4]
    assert (zlib.crc32(body) & 0xFFFFFFFF) == int.from_bytes(data[-4:], "big")
    assert data[22] == OPCODE_NUMBERS["CONST"]
    assert data[27] == OPCODE_NUMBERS["PRINT"]
    assert data[28:32] == b"\xff\xff\xff\xff"
    assert data[32] == OPCODE_NUMBERS["HALT"]


def test_serializer_int_range() -> None:
    program = compile_source("print 1;")
    program.constants[0] = 2**63 - 1
    assert loads(dumps(program)).constants[0] == 2**63 - 1
    program.constants[0] = -(2**63)
    assert loads(dumps(program)).constants[0] == -(2**63)
    program.constants[0] = 2**63
    with pytest.raises(SerializationError):
        dumps(program)
    program.constants[0] = -(2**63) - 1
    with pytest.raises(SerializationError):
        dumps(program)


def test_serializer_bad_magic_checksum_and_truncation() -> None:
    data = dumps(compile_source("print 1;"))
    with pytest.raises(SerializationError) as magic:
        loads(b"XXXX" + data[4:])
    assert "magic" in str(magic.value)
    flipped = bytearray(data)
    flipped[10] ^= 0x01
    with pytest.raises(SerializationError) as checksum:
        loads(bytes(flipped))
    assert "checksum" in str(checksum.value)
    with pytest.raises(SerializationError) as short:
        loads(data[:8])
    assert isinstance(short.value, SerializationError)
    with pytest.raises(SerializationError):
        loads(data + b"\x00")


def test_serializer_version_trailing_and_payloads() -> None:
    data = dumps(compile_source("print true;"))
    body = bytearray(data[4:-4])
    body[0] = 2
    with pytest.raises(SerializationError) as version:
        loads(_rechecksum(bytes(body)))
    assert "version" in str(version.value)
    original = bytearray(data[4:-4])
    with pytest.raises(SerializationError) as trailing:
        loads(_rechecksum(bytes(original) + b"\x00"))
    assert "trailing" in str(trailing.value)
    bad_bool = bytearray(data[4:-4])
    tag = bad_bool.index(0x04)
    bad_bool[tag + 1] = 2
    with pytest.raises(SerializationError) as flag:
        loads(_rechecksum(bytes(bad_bool)))
    assert "bool" in str(flag.value)


def test_serializer_unknown_opcode_and_argument_encoding() -> None:
    data = bytearray(dumps(compile_source("print 1;")))
    body = bytearray(data[4:-4])
    body[-5] = 99
    with pytest.raises(SerializationError) as opcode:
        loads(_rechecksum(bytes(body)))
    assert "opcode" in str(opcode.value)
    missing = bytearray(data[4:-4])
    missing[19:23] = b"\xff\xff\xff\xff"
    with pytest.raises(SerializationError) as arg:
        loads(_rechecksum(bytes(missing)))
    assert "argument" in str(arg.value)
    extra = bytearray(data[4:-4])
    extra[-4:] = b"\x00\x00\x00\x00"
    with pytest.raises(SerializationError):
        loads(_rechecksum(bytes(extra)))


def test_insane_length_does_not_trust_fields_before_checksum() -> None:
    data = bytearray(dumps(compile_source("print 1;")))
    data[5] = 0xFF
    data[6] = 0xFF
    with pytest.raises(SerializationError) as caught:
        loads(bytes(data))
    assert "checksum" in str(caught.value)


def test_float_and_string_round_trip_bits() -> None:
    program = compile_source('print 1.5; print -0.0; print "";', optimize=True)
    restored = loads(dumps(program))
    assert struct.pack(">d", restored.constants[1]) == struct.pack(">d", -0.0)
    assert restored.constants[2] == ""
    assert execute(restored) == ["1.5", "-0.0", ""]


def test_step_limit_stops_infinite_loop() -> None:
    with pytest.raises(StepLimitError) as caught:
        _run("while (true) { }", step_limit=20)
    assert isinstance(caught.value, VMRuntimeError)
    assert isinstance(caught.value, MicroVMError)
    assert _run("print 1;", step_limit=3) == ["1"]
    with pytest.raises(StepLimitError):
        _run("print 1;", step_limit=2)


def test_step_limit_must_be_positive_int() -> None:
    program = compile_source("print 1;")
    for bad in (0, -1, True, False, 1.5, "3"):
        with pytest.raises(ValueError):
            execute(program, step_limit=bad)  # type: ignore[arg-type]


def test_manual_pop_and_underflow() -> None:
    program = Program(
        [1, 2],
        [],
        [
            Instr("CONST", 0),
            Instr("CONST", 1),
            Instr("POP", None),
            Instr("PRINT", None),
            Instr("HALT", None),
        ],
    )
    assert execute(program) == ["1"]
    with pytest.raises(VMRuntimeError):
        execute(Program([], [], [Instr("PRINT", None), Instr("HALT", None)]))


def test_bad_jump_and_non_bool_condition() -> None:
    ok = Program([True], [], [Instr("CONST", 0), Instr("JUMP_IF_FALSE", 9), Instr("HALT", None)])
    assert execute(ok) == []
    bad = Program([False], [], [Instr("CONST", 0), Instr("JUMP_IF_FALSE", 9), Instr("HALT", None)])
    with pytest.raises(VMRuntimeError):
        execute(bad)
    mixed = Program([1], [], [Instr("CONST", 0), Instr("JUMP_IF_FALSE", 2), Instr("HALT", None)])
    with pytest.raises(VMRuntimeError):
        execute(mixed)


def test_empty_program_and_assignment() -> None:
    assert _run("") == []
    assert _run("// nothing\n{ }") == []
    assert _run("let x = 1; x = x * 3; print x;") == ["3"]
    assert compile_source("").instructions == [Instr("HALT", None)]


def test_fibonacci_and_nested_blocks() -> None:
    src = """
    let a = 0;
    let b = 1;
    let n = 0;
    let t = 0;
    while (n < 5) {
      print a;
      t = a + b;
      a = b;
      b = t;
      n = n + 1;
    }
    """
    assert _run(src) == ["0", "1", "1", "2", "3"]


def test_opcodes_are_exact() -> None:
    assert OPCODES == (
        "CONST", "LOAD", "STORE", "ADD", "SUB", "MUL", "DIV", "MOD", "NEG", "NOT",
        "EQ", "NE", "LT", "LE", "GT", "GE", "JUMP", "JUMP_IF_FALSE", "PRINT", "POP", "HALT",
    )
    assert OPCODE_NUMBERS["CONST"] == 1
    assert OPCODE_NUMBERS["HALT"] == 21
    assert len(OPCODE_NUMBERS) == 21
    assert len(microvm.__all__) == 19
    assert "StepLimitError" not in microvm.__all__


def test_public_exports() -> None:
    expected = [
        "tokenize", "Token", "parse", "compile_source", "Program", "Instr",
        "fold_constants", "execute", "dumps", "loads", "disassemble", "OPCODES",
        "OPCODE_NUMBERS", "MicroVMError", "LexError", "ParseError", "CompileError",
        "SerializationError", "VMRuntimeError",
    ]
    assert microvm.__all__ == expected
    for name in expected:
        assert hasattr(microvm, name)


def test_cli_run_success(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    src = tmp_path / "t.mv"
    src.write_text("let x = 5; print x; print 8 / 2;\n", encoding="utf-8")
    assert main(["run", str(src)]) == 0
    captured = capsys.readouterr()
    assert _norm(captured.out) == "5\n4.0\n"
    assert captured.err == ""


def test_cli_exit_codes(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    missing = tmp_path / "missing.mv"
    assert main(["run", str(missing)]) == 2
    assert main(["nope"]) == 2
    assert main([]) == 2
    src = tmp_path / "t.mv"
    src.write_text("print 1;\n", encoding="utf-8")
    assert main(["run", str(src), "--step-limit", "0"]) == 2
    assert main(["run", str(src), "--step-limit", "abc"]) == 2
    assert main(["run", str(src), "--step-limit", "-3"]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""


def test_cli_runtime_error_has_no_stdout(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    src = tmp_path / "bad.mv"
    src.write_text('print "before"; print 1 / 0;\n', encoding="utf-8")
    assert main(["run", str(src)]) == 3
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err != ""
    syntax = tmp_path / "syn.mv"
    syntax.write_text("print 1\n", encoding="utf-8")
    assert main(["run", str(syntax)]) == 3
    assert capsys.readouterr().out == ""


def test_cli_build_exec_disasm(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    src = tmp_path / "t.mv"
    out = tmp_path / "t.mvm"
    src.write_text("print 1 + 2 * 3;\n", encoding="utf-8")
    assert main(["build", str(src), str(out), "--optimize"]) == 0
    assert out.read_bytes() == dumps(compile_source("print 1 + 2 * 3;\n", optimize=True))
    assert main(["exec", str(out)]) == 0
    assert _norm(capsys.readouterr().out) == "7\n"
    assert main(["disasm", str(out)]) == 0
    assert capsys.readouterr().out == disassemble(loads(out.read_bytes()))


def test_cli_module_entrypoint(tmp_path: Path) -> None:
    src = tmp_path / "t.mv"
    src.write_text("let x = 5; print x; print 8 / 2;\n", encoding="utf-8")
    result = subprocess.run(
        [sys.executable, "-m", "microvm", "run", str(src)],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert _norm(result.stdout) == "5\n4.0\n"


def test_cli_step_limit_and_optimize(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    src = tmp_path / "loop.mv"
    src.write_text("while (true) { }\n", encoding="utf-8")
    assert main(["run", str(src), "--step-limit", "15"]) == 3
    assert capsys.readouterr().out == ""
    math_src = tmp_path / "math.mv"
    math_src.write_text("print 8 / 2;\n", encoding="utf-8")
    assert main(["run", str(math_src), "--optimize"]) == 0
    assert _norm(capsys.readouterr().out) == "4.0\n"


def test_parenthesized_comparison_is_allowed() -> None:
    assert _run("print (1 < 2) == true;") == ["true"]
    with pytest.raises(ParseError):
        parse("print 1 == 2 != 3;")


def test_string_ordered_and_concat_errors() -> None:
    assert _run('print "abc" > "ab"; print "a" <= "a";') == ["true", "true"]
    with pytest.raises(VMRuntimeError):
        _run('print 1 + "a";')
    with pytest.raises(VMRuntimeError):
        _run("print true * 2;")


def test_assignment_before_initializer_runs() -> None:
    assert _run("let x = 1; let y = x + 2; x = y; print x;") == ["3"]
    with pytest.raises(VMRuntimeError) as caught:
        _run("let x = x + 1;")
    assert "x" in str(caught.value)


def test_comment_between_tokens_and_keyword_idents() -> None:
    assert _run("print // hi\n 1; print 2;") == ["1", "2"]
    assert _run("let IF = 4; print IF;") == ["4"]
    program = compile_source("print (1);")
    assert [instr.op for instr in program.instructions] == ["CONST", "PRINT", "HALT"]


def test_modulo_and_div_type_matrix() -> None:
    assert _run("print 4 / 2 * 2;") == ["4.0"]
    with pytest.raises(VMRuntimeError):
        _run("print 7 % 2.0;")
    with pytest.raises(VMRuntimeError):
        _run("print true / 1;")
    with pytest.raises(VMRuntimeError):
        _run("print 1 % true;")


def test_loads_rejects_non_bytes_and_unknown_tag() -> None:
    with pytest.raises(SerializationError):
        loads("MVM1")  # type: ignore[arg-type]
    body = b"\x01\x00\x00\x00\x01\x05\x00\x00\x00\x00"
    with pytest.raises(SerializationError) as caught:
        loads(_rechecksum(body))
    assert "tag" in str(caught.value) or "truncated" in str(caught.value)


def test_fold_comparisons_and_not() -> None:
    program = compile_source("print not (1 == 2);", optimize=True)
    assert [instr.op for instr in program.instructions] == ["CONST", "PRINT", "HALT"]
    assert _run("print 1 < 2;", optimize=True) == ["true"]
    assert _run('print "a" + "b";', optimize=True) == ["ab"]
    assert _run("print true == 1;", optimize=True) == ["false"]
    with pytest.raises(VMRuntimeError):
        _run("print true < false;", optimize=True)
