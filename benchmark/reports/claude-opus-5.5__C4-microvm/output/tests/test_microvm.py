"""Tests for microvm."""

from __future__ import annotations

import struct
import subprocess
import sys
import zlib
from pathlib import Path

import pytest

import microvm
from microvm import (
    OPCODE_NUMBERS, OPCODES, CompileError, Instr, LexError, MicroVMError, ParseError,
    Program, SerializationError, Token, VMRuntimeError, compile_source, disassemble, dumps,
    execute, fold_constants, loads, parse, tokenize,
)
from microvm.__main__ import main
from microvm.errors import StepLimitError

ROOT = Path(__file__).resolve().parent.parent


def run(src: str, optimize: bool = False, step_limit: int = 100_000) -> list[str]:
    return execute(compile_source(src, optimize=optimize), step_limit=step_limit)


def both(src: str) -> list[str]:
    plain = run(src)
    assert run(src, optimize=True) == plain
    return plain


def raises_both(src: str, exc: type = VMRuntimeError) -> None:
    for optimize in (False, True):
        with pytest.raises(exc):
            run(src, optimize=optimize)


# ---------------------------------------------------------------- package / errors

def test_all_exports() -> None:
    assert len(microvm.__all__) == 19
    for name in microvm.__all__:
        assert hasattr(microvm, name)
    assert "StepLimitError" not in microvm.__all__


def test_error_hierarchy() -> None:
    for cls in (LexError, ParseError, CompileError, SerializationError, VMRuntimeError):
        assert issubclass(cls, MicroVMError)
    assert issubclass(StepLimitError, VMRuntimeError)


def test_opcode_table() -> None:
    assert len(OPCODES) == 21
    assert OPCODE_NUMBERS["CONST"] == 1 and OPCODE_NUMBERS["HALT"] == 21
    assert OPCODE_NUMBERS["JUMP_IF_FALSE"] == 18


# ---------------------------------------------------------------- lexer

def test_tokenize_basic() -> None:
    toks = tokenize("let x = 1.5e3; // comment\nprint x >= 2;")
    assert [t.kind for t in toks] == [
        "KEYWORD", "IDENT", "OP", "FLOAT", "OP", "KEYWORD", "IDENT", "OP", "INT", "OP"]
    assert toks[3].value == 1500.0 and toks[3].text == "1.5e3"
    assert toks[7] == Token("OP", ">=", ">=", 34)
    assert toks[8].value == 2 and toks[1].offset == 4


def test_tokenize_keywords_case_sensitive() -> None:
    toks = tokenize("IF if True true")
    assert [(t.kind, t.value) for t in toks] == [
        ("IDENT", "IF"), ("KEYWORD", "if"), ("IDENT", "True"), ("KEYWORD", "true")]


def test_tokenize_string_escapes() -> None:
    (tok,) = tokenize(r'"a\n\t\"\\b"')
    assert tok.kind == "STRING" and tok.value == 'a\n\t"\\b' and tok.text == tok.value
    assert tok.offset == 0


@pytest.mark.parametrize("src, offset", [
    ("1.", 0), (".5", 0), ("x = @;", 4), ('"abc', 0), ('"a\\qb"', 2), ('"a\nb"', 2),
    ("!x", 0), ("1.5e", 0),
])
def test_lex_errors(src: str, offset: int) -> None:
    with pytest.raises(LexError) as info:
        tokenize(src)
    assert info.value.offset == offset


def test_tokenize_longest_match() -> None:
    assert [t.text for t in tokenize("a==b=c!=d<=e<f")] == [
        "a", "==", "b", "=", "c", "!=", "d", "<=", "e", "<", "f"]


# ---------------------------------------------------------------- parser

@pytest.mark.parametrize("src, offset", [
    ("print 1 < 2 < 3;", 12), ("let x;", 5), ("print 1", 7), ("x;", 1),
    ("if (true) print 1;", 10), ("print (1;", 8), ("let if = 1;", 4), ("}", 0),
])
def test_parse_errors(src: str, offset: int) -> None:
    with pytest.raises(ParseError) as info:
        parse(src)
    assert info.value.offset == offset


def test_parse_lex_error_passes_through() -> None:
    with pytest.raises(LexError):
        parse("print $;")


def test_parse_accepts_else_if_chain() -> None:
    assert parse("if (true) { } else if (false) { } else { print 1; }") is not None


# ---------------------------------------------------------------- semantics

def test_arithmetic_types() -> None:
    assert both("print 1 + 2; print 1 + 2.0; print 3 * 2; print 5 - 7.5;") == [
        "3", "3.0", "6", "-2.5"]


def test_string_concat_and_mismatch() -> None:
    assert both('print "ab" + "cd";') == ["abcd"]
    raises_both('print "a" + 1;')
    raises_both('print "a" * 2;')


def test_division_always_float() -> None:
    assert both("print 7 / 2; print 4 / 2;") == ["3.5", "2.0"]


def test_modulo_sign_rule_and_types() -> None:
    assert both("print -7 % 3; print 7 % -3;") == ["2", "-2"]
    raises_both("print 7.0 % 2;")


def test_division_and_modulo_by_zero() -> None:
    raises_both("print 1 / 0;")
    raises_both("print 1 % 0;")
    raises_both("print 1.0 / 0.0;")


def test_bool_is_not_a_number() -> None:
    raises_both("print true + 1;")
    raises_both("print -true;")
    raises_both("print true < false;")


def test_unary_minus() -> None:
    assert both("let x = 3; print -x; print --2.5;") == ["-3", "2.5"]
    raises_both('print -"a";')


def test_equality_rules() -> None:
    assert both('print true == 1; print 1 == 1.0; print "1" == 1; print 1 != 2; '
                'print false != 0; print "a" == "a";') == [
        "false", "true", "false", "true", "true", "true"]


def test_ordering_rules() -> None:
    assert both('print 1 < 1.5; print "b" > "a"; print "B" < "a"; print 2 >= 2;') == [
        "true", "true", "true", "true"]
    raises_both('print 1 < "a";')


def test_logic_requires_bool() -> None:
    raises_both("let y = true and 5;")
    raises_both("let y = false or 5;")
    raises_both("print not 1;")
    raises_both("print 1 and true;")


def test_short_circuit_and() -> None:
    assert both("print false and (1 / 0 == 0);") == ["false"]
    assert both("let x = 0; print x != 0 and 10 / x > 1;") == ["false"]


def test_short_circuit_or() -> None:
    assert both("print true or (1 / 0 == 0);") == ["true"]
    assert both('let s = "x"; print s == "x" or s + 1 == 2;') == ["true"]


def test_logic_truth_table() -> None:
    lines = both("let t = true; let f = false; print t and t; print t and f; print f and t; "
                 "print f or f; print f or t; print t or f; print not f; print not not t;")
    assert lines == ["true", "false", "false", "false", "true", "true", "true", "true"]


def test_condition_must_be_bool() -> None:
    raises_both("if (1) { print 1; }")
    raises_both('while ("x") { }')


def test_print_rendering() -> None:
    assert both('print true; print false; print 1.5; print "a\\"b"; print 10;') == [
        "true", "false", "1.5", 'a"b', "10"]


def test_if_else_chain() -> None:
    src = ("let x = {v}; if (x > 5) {{ print \"big\"; }} else if (x > 2) {{ print \"mid\"; }}"
           " else {{ print \"small\"; }}")
    assert both(src.format(v=9)) == ["big"]
    assert both(src.format(v=3)) == ["mid"]
    assert both(src.format(v=1)) == ["small"]


def test_while_loop() -> None:
    assert both("let i = 0; let s = 0; while (i < 5) { i = i + 1; s = s + i; } print s;") == ["15"]


def test_blocks_do_not_scope() -> None:
    assert both("{ let x = 1; } { print x; } if (true) { let y = 2; } print y;") == ["1", "2"]


def test_precedence() -> None:
    assert both("print 1 + 2 * 3; print (1 + 2) * 3; print -2 * 3; print 10 - 4 - 3;") == [
        "7", "9", "-6", "3"]
    assert both("print not 1 < 2 or true and false;") == ["false"]


# ---------------------------------------------------------------- compile-time errors

def test_duplicate_let_is_compile_error() -> None:
    with pytest.raises(CompileError):
        compile_source("let x = 1; if (false) { let x = 2; }")


def test_undeclared_names_are_compile_errors() -> None:
    with pytest.raises(CompileError):
        compile_source("print y;")
    with pytest.raises(CompileError):
        compile_source("y = 1;")
    with pytest.raises(CompileError):
        compile_source("print false and z;", optimize=True)


def test_never_assigned_variable_runtime_error() -> None:
    for optimize in (False, True):
        program = compile_source("if (false) { let x = 1; } print x;", optimize=optimize)
        with pytest.raises(VMRuntimeError, match="x"):
            execute(program)


# ---------------------------------------------------------------- bytecode shape

def test_print_literal_is_three_instructions() -> None:
    program = compile_source("print 1;")
    assert program.instructions == [Instr("CONST", 0), Instr("PRINT", None), Instr("HALT", None)]
    assert program.constants == [1]


def test_single_halt_at_end() -> None:
    program = compile_source("let x = 1; while (x < 3) { if (x == 2) { print x; } x = x + 1; }")
    ops = [i.op for i in program.instructions]
    assert ops[-1] == "HALT" and ops.count("HALT") == 1


def test_constant_pool_dedup() -> None:
    program = compile_source("print 1; print 1.0; print true; print 1; print 1.0; print true;")
    assert len(program.constants) == 3
    assert [type(c) for c in program.constants] == [int, float, bool]


def test_names_in_declaration_order() -> None:
    assert compile_source("let b = 1; let a = 2; { let c = 3; }").names == ["b", "a", "c"]


def test_short_circuit_uses_jumps() -> None:
    ops = [i.op for i in compile_source("let a = true; print a and a;").instructions]
    assert "JUMP_IF_FALSE" in ops


# ---------------------------------------------------------------- optimizer

def test_folding_reduces_to_three_instructions() -> None:
    assert len(compile_source("print 1 + 2 * 3;").instructions) > 3
    program = compile_source("print 1 + 2 * 3;", optimize=True)
    assert [i.op for i in program.instructions] == ["CONST", "PRINT", "HALT"]
    assert program.constants == [7]


def test_folding_keeps_failing_operations() -> None:
    program = compile_source("print 1 / 0;", optimize=True)
    assert "DIV" in [i.op for i in program.instructions]
    raises_both('print "a" + 1;')


def test_folding_keeps_true_and_x_check() -> None:
    raises_both("let y = true and 5;")
    raises_both("let y = false or 5;")


def test_folding_allowed_short_circuits() -> None:
    program = compile_source("print false and (1 / 0 == 0);", optimize=True)
    assert [i.op for i in program.instructions] == ["CONST", "PRINT", "HALT"]
    assert run("print true or 5;", optimize=True) == ["true"]
    assert run("print not (true and false);", optimize=True) == ["true"]


def test_fold_constants_on_ast() -> None:
    tree = parse("print 2 * 3;")
    assert fold_constants(tree) != tree
    assert fold_constants(fold_constants(tree)) == fold_constants(tree)


def test_folding_preserves_float_and_bool_types() -> None:
    assert both("print 1 + 1.0; print 3 == 3.0; print -0.0; print 0.0;") == [
        "2.0", "true", "-0.0", "0.0"]


# ---------------------------------------------------------------- VM

def test_step_limit_infinite_loop() -> None:
    with pytest.raises(StepLimitError):
        run("while (true) { }", step_limit=1000)


def test_step_limit_exact_boundary() -> None:
    program = compile_source("print 1;")
    assert execute(program, step_limit=3) == ["1"]
    with pytest.raises(StepLimitError):
        execute(program, step_limit=2)


@pytest.mark.parametrize("bad", [0, -1, True, 1.5, "10"])
def test_step_limit_validation(bad: object) -> None:
    with pytest.raises(ValueError):
        execute(compile_source("print 1;"), step_limit=bad)  # type: ignore[arg-type]


def test_vm_rejects_malformed_program() -> None:
    with pytest.raises(VMRuntimeError):
        execute(Program([], [], [Instr("ADD", None), Instr("HALT", None)]))
    with pytest.raises(VMRuntimeError):
        execute(Program([], [], [Instr("JUMP", 99)]))


# ---------------------------------------------------------------- serializer

SAMPLE = ('let s = "hé\\n"; let i = 0; while (i < 3) { i = i + 1; } '
          'print i; print 2.5; print true and i == 3; print "é" + "x"; print -9;')


def test_serializer_round_trip() -> None:
    for optimize in (False, True):
        program = compile_source(SAMPLE, optimize=optimize)
        data = dumps(program)
        again = loads(data)
        assert again == program
        assert execute(again) == execute(program)
        assert dumps(again) == data


def test_serializer_layout() -> None:
    data = dumps(compile_source("print 1;"))
    assert data[:4] == b"MVM1" and data[4] == 1
    assert struct.unpack(">I", data[-4:])[0] == zlib.crc32(data[4:-4])
    body = data[5:-4]
    assert body[:4] == b"\x00\x00\x00\x01"  # no names, one constant
    assert body[4:13] == b"\x01" + struct.pack(">q", 1)
    assert body[13:17] == struct.pack(">I", 3)
    assert body[17:22] == b"\x01\x00\x00\x00\x00"
    assert body[22:27] == b"\x13\xff\xff\xff\xff"


def test_serializer_int_out_of_range() -> None:
    with pytest.raises(SerializationError):
        dumps(Program([2 ** 63], [], [Instr("HALT", None)]))
    assert loads(dumps(Program([-(2 ** 63)], [], [Instr("HALT", None)]))).constants == [-(2 ** 63)]


def _resign(body: bytes) -> bytes:
    return b"MVM1" + body + struct.pack(">I", zlib.crc32(body))


def test_loads_corruption_cases() -> None:
    data = dumps(compile_source("let x = 1; print x;"))
    corrupt = [
        b"XVM1" + data[4:],                     # bad magic
        data[:-1],                              # truncated
        data[:10],                              # badly truncated
        data + b"\x00",                         # trailing byte
        data[:8] + bytes([data[8] ^ 0xFF]) + data[9:],  # flipped bit -> checksum
        _resign(b"\x02" + data[5:-4]),          # unsupported version
        b"",
    ]
    for blob in corrupt:
        with pytest.raises(SerializationError):
            loads(blob)


def test_loads_semantic_corruption_with_valid_checksum() -> None:
    header = b"\x01\x00\x00"
    cases = [
        header + b"\x00\x01\x09" + b"\x00" * 8 + b"\x00\x00\x00\x00",   # unknown tag
        header + b"\x00\x01\x04\x02" + b"\x00\x00\x00\x00",             # bad bool
        header + b"\x00\x00" + b"\x00\x00\x00\x01" + b"\x63\xff\xff\xff\xff",  # opcode 99
        header + b"\x00\x00" + b"\x00\x00\x00\x01" + b"\x01\xff\xff\xff\xff",  # CONST no arg
        header + b"\x00\x00" + b"\x00\x00\x00\x01" + b"\x15\x00\x00\x00\x00",  # HALT w/ arg
        header + b"\x00\x00" + b"\x00\x00\xff\xff",                     # count too large
        header + b"\x00\x00" + b"\x00\x00\x00\x00" + b"\x00",           # trailing in body
    ]
    for body in cases:
        with pytest.raises(SerializationError):
            loads(_resign(body))


def test_dumps_is_deterministic() -> None:
    assert dumps(compile_source(SAMPLE)) == dumps(compile_source(SAMPLE))


# ---------------------------------------------------------------- disassembler

def test_disassemble_exact() -> None:
    assert disassemble(compile_source("print 1;")) == "0000 CONST 0  ; 1\n0001 PRINT\n0002 HALT\n"


def test_disassemble_constant_rendering() -> None:
    program = Program(["a\"b\\\n\t", True, 2.5], ["x"],
                      [Instr("CONST", 0), Instr("CONST", 1), Instr("CONST", 2),
                       Instr("STORE", 0), Instr("JUMP", 5), Instr("HALT", None)])
    assert disassemble(program).splitlines() == [
        '0000 CONST 0  ; "a\\"b\\\\\\n\\t"', "0001 CONST 1  ; true", "0002 CONST 2  ; 2.5",
        "0003 STORE 0", "0004 JUMP 5", "0005 HALT"]


# ---------------------------------------------------------------- CLI

def _write(tmp_path: Path, name: str, text: str) -> str:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return str(path)


def test_cli_run(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    src = _write(tmp_path, "t.mv", "let x = 5; print x; print 8 / 2;")
    assert main(["run", src]) == 0
    assert capsys.readouterr().out == "5\n4.0\n"


def test_cli_runtime_error_prints_nothing(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    src = _write(tmp_path, "t.mv", "print 1; print 1 / 0;")
    assert main(["run", src]) == 3
    captured = capsys.readouterr()
    assert captured.out == "" and captured.err


def test_cli_step_limit(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    src = _write(tmp_path, "t.mv", "print 1; while (true) { }")
    assert main(["run", src, "--step-limit", "50"]) == 3
    assert capsys.readouterr().out == ""
    for bad in ("0", "-3", "abc"):
        assert main(["run", src, "--step-limit", bad]) == 2


def test_cli_usage_errors(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    assert main([]) == 2
    assert main(["frobnicate"]) == 2
    assert main(["run"]) == 2
    assert main(["run", str(tmp_path / "missing.mv")]) == 2
    assert main(["build", _write(tmp_path, "a.mv", "print 1;")]) == 2
    assert capsys.readouterr().out == ""


def test_cli_compile_errors_exit_3(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    for text in ("print @;", "print 1 < 2 < 3;", "print y;"):
        assert main(["run", _write(tmp_path, "e.mv", text)]) == 3
    assert capsys.readouterr().out == ""


def test_cli_build_exec_disasm(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    src = _write(tmp_path, "p.mv", "print 1 + 2 * 3;")
    out = str(tmp_path / "p.mvb")
    assert main(["build", src, out, "--optimize"]) == 0
    assert main(["exec", out]) == 0
    assert main(["disasm", out]) == 0
    assert capsys.readouterr().out == "7\n0000 CONST 0  ; 7\n0001 PRINT\n0002 HALT\n"


def test_cli_exec_corrupt_binary(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    bad = tmp_path / "bad.mvb"
    bad.write_bytes(b"MVM1garbage")
    assert main(["exec", str(bad)]) == 3
    assert main(["disasm", str(bad)]) == 3
    assert capsys.readouterr().out == ""


def test_cli_as_module(tmp_path: Path) -> None:
    src = _write(tmp_path, "t.mv", "let x = 5; print x; print 8 / 2;")
    result = subprocess.run([sys.executable, "-m", "microvm", "run", src],
                            capture_output=True, text=True, cwd=ROOT)
    assert result.returncode == 0 and result.stdout.splitlines() == ["5", "4.0"]
    result = subprocess.run([sys.executable, "-m", "microvm", "bogus"],
                            capture_output=True, text=True, cwd=ROOT)
    assert result.returncode == 2 and result.stdout == ""
