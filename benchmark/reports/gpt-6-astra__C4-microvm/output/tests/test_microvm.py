from __future__ import annotations

from dataclasses import FrozenInstanceError
import importlib
import inspect
import io
from pathlib import Path
import struct
import subprocess
import sys
import tokenize as python_tokenize
import zlib

import pytest

import microvm
from microvm import (
    CompileError, Instr, LexError, MicroVMError, OPCODES, OPCODE_NUMBERS,
    ParseError, Program, SerializationError, Token, VMRuntimeError,
    compile_source, disassemble, dumps, execute, fold_constants, loads, parse,
    tokenize,
)
from microvm.__main__ import main
from microvm.errors import StepLimitError


def _run(source: str, optimize: bool = False) -> list[str]:
    return execute(compile_source(source, optimize=optimize))


def _envelope(body: bytes) -> bytes:
    return b"MVM1" + body + struct.pack(">I", zlib.crc32(body))


def _body(constants: bytes = b"", count: int = 0, code: bytes | None = None) -> bytes:
    if code is None:
        code = bytes((21,)) + b"\xff" * 4
    return b"\x01\x00\x00" + struct.pack(">H", count) + constants + struct.pack(">I", len(code) // 5) + code


def _source(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "source.mv"
    path.write_text(text, encoding="utf-8")
    return path


def test_exports() -> None:
    expected = (
        "tokenize Token parse compile_source Program Instr fold_constants execute "
        "dumps loads disassemble OPCODES OPCODE_NUMBERS MicroVMError LexError "
        "ParseError CompileError SerializationError VMRuntimeError"
    ).split()
    assert microvm.__all__ == expected
    assert len(expected) == 19
    assert all(hasattr(microvm, name) for name in expected)


def test_error_hierarchy() -> None:
    for error in (LexError, ParseError, CompileError, SerializationError, VMRuntimeError):
        assert issubclass(error, MicroVMError)
    assert issubclass(StepLimitError, VMRuntimeError)
    assert LexError("bad", 4).offset == 4
    assert ParseError("bad", 8).offset == 8


def test_opcode_table() -> None:
    assert OPCODES == (
        "CONST", "LOAD", "STORE", "ADD", "SUB", "MUL", "DIV", "MOD", "NEG", "NOT",
        "EQ", "NE", "LT", "LE", "GT", "GE", "JUMP", "JUMP_IF_FALSE", "PRINT", "POP", "HALT",
    )
    assert OPCODE_NUMBERS == {name: index + 1 for index, name in enumerate(OPCODES)}


def test_dataclasses() -> None:
    token = Token("INT", "1", 1, 0)
    instr = Instr("HALT", None)
    with pytest.raises(FrozenInstanceError):
        token.kind = "FLOAT"
    with pytest.raises(FrozenInstanceError):
        instr.op = "PRINT"
    program = Program([], [], [instr])
    program.names = ["x"]
    assert program.names == ["x"]


def test_empty_token_stream() -> None:
    assert tokenize("") == []
    assert tokenize(" \r\n\t // comment") == []


def test_token_offsets_and_values() -> None:
    assert tokenize("let x = 12;") == [
        Token("KEYWORD", "let", "let", 0), Token("IDENT", "x", "x", 4),
        Token("OP", "=", "=", 6), Token("INT", "12", 12, 8),
        Token("OP", ";", ";", 10),
    ]


def test_keywords_and_case() -> None:
    words = "let print if else while true false and or not"
    assert all(token.kind == "KEYWORD" for token in tokenize(words))
    assert all(token.kind == "IDENT" for token in tokenize("IF True LET _x x2"))
    assert _run("let IF = 2; print IF;") == ["2"]


def test_comments_and_division() -> None:
    assert _run("print 8 / 2; // ignored\n // also ignored\nprint 1;") == ["4.0", "1"]
    assert tokenize("// skip\rprint")[0].offset == 8
    assert _run('print "//not a comment";') == ["//not a comment"]


def test_float_lexing() -> None:
    tokens = tokenize("001 1.5e3 2.0E-2 3.0e+2")
    assert [token.value for token in tokens] == [1, 1500.0, 0.02, 300.0]
    assert [token.kind for token in tokens] == ["INT", "FLOAT", "FLOAT", "FLOAT"]
    assert tokens[2].text == "2.0E-2"


@pytest.mark.parametrize("source", ["1.", ".5", "1.5e", "1.5e+", "2.0E-", "1.2.3"])
def test_invalid_numbers(source: str) -> None:
    with pytest.raises(LexError) as error:
        tokenize(source)
    assert type(error.value.offset) is int


def test_string_decoding() -> None:
    token = tokenize(r' "a\nb\t\"c\\d"')[0]
    assert token == Token("STRING", 'a\nb\t"c\\d', 'a\nb\t"c\\d', 1)
    assert tokenize('""')[0].value == ""


@pytest.mark.parametrize("source", ['"abc', '"a\nb"', '"a\rb"', r'"\q"', r'"\r"', '"abc\\'])
def test_invalid_strings(source: str) -> None:
    with pytest.raises(LexError):
        tokenize(source)


def test_longest_operator_match() -> None:
    text = "+ - * / % ( ) { } ; = == != < <= > >="
    assert [token.text for token in tokenize(text)] == text.split()
    assert [token.text for token in tokenize("===")] == ["==", "="]


@pytest.mark.parametrize("character", ["!", ".", "@", "&", "|", "'", "\u00e9"])
def test_unexpected_character_offset(character: str) -> None:
    with pytest.raises(LexError) as error:
        tokenize("  " + character)
    assert error.value.offset == 2


def test_empty_program() -> None:
    assert parse("") is not None
    program = compile_source("// nothing")
    assert program == Program([], [], [Instr("HALT", None)])
    assert execute(program) == []


@pytest.mark.parametrize("source", [
    "let x;", "let = 1;", "let if = 1;", "x 1;", "print ;", "print 1",
    "if true {}", "if (true) print 1;", "else {}", "while (true) print 1;",
    "{", "}", ";", "print (1;", "print 1);", "print +1;", "print and true;",
    "if (true) {} else print 2;", "let x = ;", "true;", 'print "print" "else";',
])
def test_malformed_programs(source: str) -> None:
    with pytest.raises(ParseError) as error:
        parse(source)
    assert 0 <= error.value.offset <= len(source)


def test_parser_error_offsets() -> None:
    with pytest.raises(ParseError) as missing:
        parse("print 1")
    assert missing.value.offset == 7
    with pytest.raises(ParseError) as bad:
        parse("print ;")
    assert bad.value.offset == 6


def test_lexer_error_passes_through_parser() -> None:
    with pytest.raises(LexError) as error:
        parse("print @;")
    assert error.value.offset == 6


@pytest.mark.parametrize("source", ["print 1 < 2 < 3;", "print 1 == 1 != 2;"])
def test_comparison_chaining_rejected(source: str) -> None:
    with pytest.raises(ParseError):
        parse(source)


def test_parenthesized_comparisons() -> None:
    assert _run("print (1 < 2) == true;") == ["true"]


def test_arithmetic_precedence_and_associativity() -> None:
    assert _run("print 1 + 2 * 3; print (1 + 2) * 3; print 10 - 3 - 2;") == ["7", "9", "5"]
    assert _run("print 20 / 2 / 2; print 2 * -3; print --2;") == ["5.0", "-6", "2"]


def test_logical_precedence() -> None:
    assert _run("print not 1 == 2 and false or true;") == ["true"]
    assert _run("print true or false and false; print not not true;") == ["true", "true"]
    assert _run("print not 1 + 2 < 4;") == ["false"]


def test_strings_resembling_syntax() -> None:
    assert _run('print "if"; print "not"; print "+"; print "("; print "==";') == [
        "if", "not", "+", "(", "==",
    ]


def test_declaration_assignment_and_print() -> None:
    assert _run("let x = 1 + 2; x = x * 3; print x;") == ["9"]
    assert _run("let x = 5; print x; print 8 / 2;") == ["5", "4.0"]


def test_blocks_are_global() -> None:
    assert _run("{ let x = 2; } x = x + 1; { print x; }") == ["3"]


def test_forward_declaration_is_global() -> None:
    assert _run("x = 7; print x; let x = 2; print x;") == ["7", "2"]


@pytest.mark.parametrize("source", [
    "let x = 1; let x = 2;", "if (true) { let x = 1; } else { let x = 2; }",
    "{ let x = 1; } { let x = 2; }",
])
def test_duplicate_declarations(source: str) -> None:
    with pytest.raises(CompileError, match="x"):
        compile_source(source)


@pytest.mark.parametrize("source", [
    "print x;", "x = 1;", "if (false) { print x; }",
    "print false and missing;", "print true or missing;",
])
@pytest.mark.parametrize("optimize", [False, True])
def test_undeclared_names(source: str, optimize: bool) -> None:
    with pytest.raises(CompileError):
        compile_source(source, optimize=optimize)


@pytest.mark.parametrize("source", [
    "if (false) { let ghost = 1; } print ghost;",
    "while (false) { let ghost = 1; } print ghost;",
    "print ghost; let ghost = 1;",
    "let ghost = ghost;",
])
def test_never_assigned_variable(source: str) -> None:
    with pytest.raises(VMRuntimeError, match="ghost"):
        _run(source)


def test_assignment_after_skipped_declaration() -> None:
    assert _run("if (false) { let x = 1; } x = 9; print x;") == ["9"]
    assert _run("if (false) { let x = 1; } print false and x;") == ["false"]


def test_declaration_slot_order() -> None:
    source = "let z = 0; if (false) { let a = 1; } else { let b = 2; } let c = 3;"
    assert compile_source(source).names == ["z", "a", "b", "c"]


@pytest.mark.parametrize("value, expected", [(8, "big"), (4, "mid"), (1, "small")])
def test_if_else_if(value: int, expected: str) -> None:
    source = (
        f"let x = {value};"
        'if (x > 5) { print "big"; } else if (x > 2) { print "mid"; }'
        'else { print "small"; }'
    )
    assert _run(source) == [expected]


def test_if_without_else() -> None:
    assert _run("if (false) { print 1; } if (true) { print 2; } print 3;") == ["2", "3"]


def test_while_loop() -> None:
    assert _run("let x = 3; while (x > 0) { print x; x = x - 1; }") == ["3", "2", "1"]


def test_nested_control_flow() -> None:
    source = (
        "let x = 0; let sum = 0; while (x < 5) {"
        "if (x % 2 == 0) { sum = sum + x; } x = x + 1; } print sum;"
    )
    assert _run(source) == ["6"]
    assert _run(source, True) == ["6"]


@pytest.mark.parametrize("expression, expected", [
    ("2 + 3", "5"), ("2 - 3", "-1"), ("2 * 3", "6"),
    ("2 + 3.5", "5.5"), ("2.0 - 3", "-1.0"), ("2 * 3.0", "6.0"),
    ("-2", "-2"), ("-2.5", "-2.5"),
])
def test_numeric_operations(expression: str, expected: str) -> None:
    assert _run(f"print {expression};") == [expected]


def test_string_concatenation() -> None:
    assert _run('print "ab" + "cd"; print "" + "x";') == ["abcd", "x"]


@pytest.mark.parametrize("expression", [
    "true + 1", "1 - false", "true * true", '1 + "a"', '"a" + 1',
    '"a" - "b"', '"a" * 2', "true / 1", "-true", '-"a"',
])
@pytest.mark.parametrize("optimize", [False, True])
def test_arithmetic_type_errors(expression: str, optimize: bool) -> None:
    with pytest.raises(VMRuntimeError):
        _run(f"print {expression};", optimize)


def test_division_always_float() -> None:
    assert _run("print 7 / 2; print 4 / 2; print 4.0 / 2;") == ["3.5", "2.0", "2.0"]


def test_modulo_sign_rule() -> None:
    assert _run("print -7 % 3; print 7 % -3; print -7 % -3;") == ["2", "-2", "-1"]


@pytest.mark.parametrize("expression", ["2.0 % 1", "2 % 1.0", "true % 1", "2 % false"])
def test_modulo_requires_int(expression: str) -> None:
    with pytest.raises(VMRuntimeError):
        _run(f"print {expression};")


@pytest.mark.parametrize("expression", ["1 / 0", "1 / 0.0", "1 / -0.0", "1 % 0"])
@pytest.mark.parametrize("optimize", [False, True])
def test_zero_division_errors(expression: str, optimize: bool) -> None:
    program = compile_source(f"print {expression};", optimize=optimize)
    with pytest.raises(VMRuntimeError, match="zero"):
        execute(program)


@pytest.mark.parametrize("expression, expected", [
    ("true == 1", "false"), ("false == 0.0", "false"), ("1 == 1.0", "true"),
    ('"1" == 1', "false"), ("true != 1", "true"), ("1 != 1.0", "false"),
    ('"a" == "a"', "true"), ("false == false", "true"), ('"x" != true', "true"),
])
def test_equality_types(expression: str, expected: str) -> None:
    assert _run(f"print {expression};") == [expected]
    assert _run(f"print {expression};", True) == [expected]


@pytest.mark.parametrize("expression", [
    "1 < 2.0", "2.0 <= 2", "3 > 2", "3.0 >= 3", '"A" < "a"', '"aa" <= "ab"',
    '"z" > "a"', '"x" >= "x"',
])
def test_ordering(expression: str) -> None:
    assert _run(f"print {expression};") == ["true"]


@pytest.mark.parametrize("expression", [
    "true < false", "true <= 1", "1 > false", '"a" >= 1', '1 < "2"', '"a" < true',
])
@pytest.mark.parametrize("optimize", [False, True])
def test_invalid_ordering(expression: str, optimize: bool) -> None:
    with pytest.raises(VMRuntimeError):
        _run(f"print {expression};", optimize)


@pytest.mark.parametrize("optimize", [False, True])
def test_short_circuit_avoids_rhs(optimize: bool) -> None:
    source = "print false and (1 / 0 == 0); print true or (1 / 0 == 0);"
    assert _run(source, optimize) == ["false", "true"]
    assert _run('print false and 5; print true or "x";', optimize) == ["false", "true"]


@pytest.mark.parametrize("expression", [
    "true and 5", "false or 5", "1 and true", '"" or true', "not 1", "not 0.0",
    "true and (false or 5)", "false or (true and 5)",
])
@pytest.mark.parametrize("optimize", [False, True])
def test_logical_strict_bool(expression: str, optimize: bool) -> None:
    with pytest.raises(VMRuntimeError, match="BOOL"):
        _run(f"let y = {expression}; print y;", optimize)


def test_logical_truth_tables() -> None:
    for left in (False, True):
        for right in (False, True):
            a, b = str(left).lower(), str(right).lower()
            expected = [str(left and right).lower(), str(left or right).lower()]
            source = f"print {a} and {b}; print {a} or {b};"
            assert _run(source) == expected
            assert _run(source, True) == expected


def test_logical_evaluation_order() -> None:
    source = "if (false) { let rhs = true; } print 1 and rhs;"
    with pytest.raises(VMRuntimeError, match="BOOL"):
        _run(source)


def test_logical_stack_balance() -> None:
    source = (
        "let n = 0; while (n < 20 and true) {"
        "print (n % 2 == 0 or false) == (not (n % 2 != 0)); n = n + 1; }"
    )
    assert _run(source) == ["true"] * 20


@pytest.mark.parametrize("condition", ["1", "0", '""', '"yes"', "1.0"])
@pytest.mark.parametrize("statement", ["if", "while"])
def test_conditions_require_bool(condition: str, statement: str) -> None:
    with pytest.raises(VMRuntimeError, match="BOOL"):
        _run(f"{statement} ({condition}) {{}}")


def test_print_rendering() -> None:
    assert _run(r'print 12; print 4 / 2; print true; print false; print "a\nb\t";') == [
        "12", "2.0", "true", "false", "a\nb\t",
    ]


def test_large_integers_execute() -> None:
    value = 1 << 100
    assert _run(f"print {value} + 1;") == [str(value + 1)]


def test_constant_pool_deduplicates_by_type() -> None:
    program = compile_source("print 1; print 1.0; print true; print 1; print 1.0; print true;")
    assert [(type(value), value) for value in program.constants] == [
        (int, 1), (float, 1.0), (bool, True),
    ]
    assert [instr.arg for instr in program.instructions if instr.op == "CONST"] == [0, 1, 2, 0, 1, 2]


def test_constant_pool_strings_and_zero() -> None:
    program = compile_source('print "x"; print "x"; print 0; print false; print 0.0;')
    assert [(type(value), value) for value in program.constants] == [
        (str, "x"), (int, 0), (bool, False), (float, 0.0),
    ]


def test_literal_instruction_contract() -> None:
    for source, value in [("1", 1), ("1.0", 1.0), ("true", True), ('"x"', "x")]:
        for optimize in (False, True):
            assert compile_source(f"print {source};", optimize=optimize) == Program(
                [value], [], [Instr("CONST", 0), Instr("PRINT", None), Instr("HALT", None)],
            )


def test_single_terminal_halt_and_valid_jumps() -> None:
    source = "let x = 0; while (x < 2) { if (true or false) { x = x + 1; } }"
    program = compile_source(source)
    assert program.instructions[-1] == Instr("HALT", None)
    assert sum(instr.op == "HALT" for instr in program.instructions) == 1
    for instr in program.instructions:
        assert instr.op in OPCODES
        if instr.op in ("JUMP", "JUMP_IF_FALSE"):
            assert instr.arg is not None and 0 <= instr.arg < len(program.instructions)


def test_short_circuit_uses_jumps() -> None:
    for expression in ("true and false", "true or false"):
        instructions = compile_source(f"print {expression};").instructions
        assert any(instr.op == "JUMP_IF_FALSE" for instr in instructions)
        assert any(instr.op == "JUMP" for instr in instructions)


def test_recursive_constant_folding() -> None:
    program = compile_source("print 1 + 2 * 3;", optimize=True)
    assert program == Program([7], [], [Instr("CONST", 0), Instr("PRINT"), Instr("HALT")])
    assert len(compile_source("print 1 + 2 * 3;").instructions) > 3
    assert fold_constants(parse("print 1 + 2 * 3;")) == parse("print 7;")


@pytest.mark.parametrize("expression, expected", [
    ('"a" + "b"', "ab"), ("-(2 + 3)", "-5"), ("not (1 > 2)", "true"),
    ("7 / 2", "3.5"), ("-7 % 3", "2"), ("true and false", "false"),
    ("false or true", "true"), ("1 == 1.0", "true"),
])
def test_fold_supported_operations(expression: str, expected: str) -> None:
    program = compile_source(f"print {expression};", optimize=True)
    assert len(program.instructions) == 3
    assert execute(program) == [expected]


def test_fold_short_circuit_eliminates_dead_rhs() -> None:
    for source, value in [("false and (1 / 0 == 0)", False), ("true or (1 / 0 == 0)", True)]:
        program = compile_source(f"print {source};", optimize=True)
        assert len(program.instructions) == 3
        assert program.constants == [value]


def test_folding_does_not_propagate_variables() -> None:
    program = compile_source("let x = 1; print x + 2;", optimize=True)
    assert any(instr.op == "ADD" for instr in program.instructions)


def test_fold_safety_preserves_failures() -> None:
    for expression, opcode in [("1 / 0", "DIV"), ('"a" + 1', "ADD"), ("not 5", "NOT")]:
        program = compile_source(f"print {expression};", optimize=True)
        assert any(instr.op == opcode for instr in program.instructions)
        with pytest.raises(VMRuntimeError):
            execute(program)


def test_fold_preserves_negative_zero() -> None:
    source = "print 0.0; print -0.0; print 0.0 * -1.0; print 0.0 / -1.0;"
    assert _run(source) == ["0.0", "-0.0", "-0.0", "-0.0"]
    assert _run(source, True) == _run(source)


def test_optimizer_input_validation() -> None:
    with pytest.raises(TypeError):
        fold_constants(None)


@pytest.mark.parametrize("limit", [0, -1, True, False, 1.5, "1", None])
def test_step_limit_validation(limit: object) -> None:
    with pytest.raises(ValueError):
        execute(compile_source(""), step_limit=limit)


def test_infinite_loop_step_limit() -> None:
    with pytest.raises(StepLimitError):
        execute(compile_source("while (true) {}"), step_limit=25)


def test_exact_step_budget_includes_halt() -> None:
    program = compile_source("print 1;")
    assert execute(program, step_limit=3) == ["1"]
    with pytest.raises(StepLimitError):
        execute(program, step_limit=2)
    assert execute(compile_source(""), step_limit=1) == []


def test_vm_pop_opcode() -> None:
    assert execute(Program([1], [], [Instr("CONST", 0), Instr("POP"), Instr("HALT")])) == []


@pytest.mark.parametrize("instructions", [
    [Instr("PRINT")], [Instr("ADD")], [Instr("CONST", 0)], [Instr("JUMP", -1)],
    [Instr("UNKNOWN")], [Instr("HALT", 1)], [Instr("LOAD", 0)],
])
def test_vm_malformed_instructions(instructions: list[Instr]) -> None:
    with pytest.raises(VMRuntimeError):
        execute(Program([], [], instructions))


def test_serializer_round_trip() -> None:
    source = (
        'let x = 3; let s = "line\\n\\t\\"\\\\"; print s; '
        "while (x > 0) { print x / 2; x = x - 1; } print true;"
    )
    for optimize in (False, True):
        program = compile_source(source, optimize=optimize)
        restored = loads(dumps(program))
        assert restored == program
        assert execute(restored) == execute(program)


def test_serializer_deterministic() -> None:
    program = compile_source("let x = 1; print x;")
    assert dumps(program) == dumps(program)
    assert dumps(loads(dumps(program))) == dumps(program)


def test_serializer_exact_layout_and_checksum() -> None:
    expected_body = (
        b"\x01\x00\x00\x00\x01\x01" + struct.pack(">q", 1) + struct.pack(">I", 3)
        + b"\x01\x00\x00\x00\x00" + b"\x13\xff\xff\xff\xff" + b"\x15\xff\xff\xff\xff"
    )
    data = dumps(compile_source("print 1;"))
    assert data == _envelope(expected_body)
    assert isinstance(data, bytes)


def test_serializer_all_constant_types() -> None:
    values = [-(1 << 63), (1 << 63) - 1, 2.5, "snow \u2603", False, True, ""]
    program = Program(values, ["\u03bb"], [Instr("HALT")])
    restored = loads(dumps(program))
    assert [(type(value), value) for value in restored.constants] == [
        (type(value), value) for value in values
    ]
    assert restored.names == ["\u03bb"]


def test_serializer_special_floats() -> None:
    program = Program([float("inf"), float("-inf"), float("nan"), -0.0], [], [Instr("HALT")])
    assert dumps(loads(dumps(program))) == dumps(program)


@pytest.mark.parametrize("value", [-(1 << 63) - 1, 1 << 63])
def test_serializer_integer_overflow(value: int) -> None:
    with pytest.raises(SerializationError):
        dumps(Program([value], [], [Instr("HALT")]))


@pytest.mark.parametrize("value", [None, [], b"x", complex(1, 2)])
def test_serializer_rejects_unsupported_constants(value: object) -> None:
    with pytest.raises(SerializationError):
        dumps(Program([value], [], [Instr("HALT")]))


def test_serializer_rejects_oversized_names_and_counts() -> None:
    for program in [
        Program([], ["a" * 65536], [Instr("HALT")]),
        Program([], ["x"] * 65536, [Instr("HALT")]),
        Program([1] * 65536, [], [Instr("HALT")]),
    ]:
        with pytest.raises(SerializationError):
            dumps(program)


def test_serializer_rejects_invalid_unicode() -> None:
    for program in [Program(["\ud800"], [], []), Program([], ["\ud800"], [])]:
        with pytest.raises(SerializationError):
            dumps(program)


@pytest.mark.parametrize("instr", [
    Instr("UNKNOWN"), Instr("CONST"), Instr("LOAD", -1), Instr("STORE", True),
    Instr("JUMP", 0xFFFFFFFF), Instr("JUMP_IF_FALSE", 1 << 32), Instr("HALT", 0),
])
def test_serializer_rejects_invalid_instruction_arguments(instr: Instr) -> None:
    with pytest.raises(SerializationError):
        dumps(Program([], [], [instr]))


def test_bad_magic() -> None:
    data = dumps(compile_source(""))
    with pytest.raises(SerializationError, match="magic"):
        loads(b"NOPE" + data[4:])


def test_bad_version_with_valid_checksum() -> None:
    body = bytearray(_body())
    body[0] = 2
    with pytest.raises(SerializationError, match="version"):
        loads(_envelope(body))


def test_checksum_mismatch() -> None:
    data = bytearray(dumps(compile_source("print 1;")))
    data[10] ^= 1
    with pytest.raises(SerializationError, match="checksum"):
        loads(bytes(data))


def test_checksum_checked_before_lengths() -> None:
    data = bytearray(dumps(compile_source("")))
    data[5:7] = b"\xff\xff"
    with pytest.raises(SerializationError, match="checksum"):
        loads(bytes(data))


def test_unknown_constant_tag() -> None:
    with pytest.raises(SerializationError, match="tag"):
        loads(_envelope(_body(b"\x99", 1)))


@pytest.mark.parametrize("payload", [2, 128, 255])
def test_invalid_bool_payload(payload: int) -> None:
    with pytest.raises(SerializationError, match="BOOL"):
        loads(_envelope(_body(bytes((4, payload)), 1)))


@pytest.mark.parametrize("opcode", [0, 22, 255])
def test_unknown_opcode_number(opcode: int) -> None:
    with pytest.raises(SerializationError, match="opcode"):
        loads(_envelope(_body(code=bytes((opcode,)) + b"\xff" * 4)))


@pytest.mark.parametrize("op", ["CONST", "LOAD", "STORE", "JUMP", "JUMP_IF_FALSE"])
def test_missing_encoded_argument(op: str) -> None:
    code = bytes((OPCODE_NUMBERS[op],)) + b"\xff" * 4
    with pytest.raises(SerializationError, match="argument"):
        loads(_envelope(_body(code=code)))


@pytest.mark.parametrize("op", [op for op in OPCODES if op not in ("CONST", "LOAD", "STORE", "JUMP", "JUMP_IF_FALSE")])
def test_unexpected_encoded_argument(op: str) -> None:
    code = bytes((OPCODE_NUMBERS[op],)) + b"\x00" * 4
    with pytest.raises(SerializationError, match="argument"):
        loads(_envelope(_body(code=code)))


def test_every_truncated_prefix() -> None:
    data = dumps(compile_source('let x = 1; print "hello"; print x / 2; print false;'))
    for length in range(len(data)):
        with pytest.raises(SerializationError):
            loads(data[:length])


def test_truncated_body_with_recomputed_checksum() -> None:
    body = dumps(compile_source('let x = 1; print "hello"; print 1.5; print true;'))[4:-4]
    for length in range(len(body)):
        with pytest.raises(SerializationError):
            loads(_envelope(body[:length]))


def test_trailing_bytes() -> None:
    data = dumps(compile_source(""))
    with pytest.raises(SerializationError):
        loads(data + b"extra")
    with pytest.raises(SerializationError, match="Trailing"):
        loads(_envelope(data[4:-4] + b"extra"))


def test_hostile_lengths_with_valid_checksum() -> None:
    for body in [
        b"\x01\xff\xff",
        b"\x01\x00\x01\xff\xffx",
        _body(b"\x03\xff\xff\xff\xffx", 1),
        b"\x01\x00\x00\x00\x00\xff\xff\xff\xff",
    ]:
        with pytest.raises(SerializationError):
            loads(_envelope(body))


def test_invalid_encoded_utf8() -> None:
    for body in [
        b"\x01\x00\x01\x00\x01\xff\x00\x00\x00\x00\x00\x00",
        _body(b"\x03\x00\x00\x00\x01\xff", 1),
    ]:
        with pytest.raises(SerializationError, match="UTF-8"):
            loads(_envelope(body))


def test_exact_disassembly() -> None:
    assert disassemble(compile_source("print 1;")) == (
        "0000 CONST 0  ; 1\n0001 PRINT\n0002 HALT\n"
    )


def test_disassembly_escaped_strings_and_types() -> None:
    source = r'print "a\nb\t\"c\\d"; print true; print false; print 1.0;'
    assert disassemble(compile_source(source)) == (
        '0000 CONST 0  ; "a\\nb\\t\\"c\\\\d"\n0001 PRINT\n'
        "0002 CONST 1  ; true\n0003 PRINT\n"
        "0004 CONST 2  ; false\n0005 PRINT\n"
        "0006 CONST 3  ; 1.0\n0007 PRINT\n0008 HALT\n"
    )


def test_disassembly_arguments_and_empty_program() -> None:
    program = Program([], ["x"], [Instr("LOAD", 0), Instr("STORE", 0), Instr("JUMP", 3), Instr("HALT")])
    assert disassemble(program) == "0000 LOAD 0\n0001 STORE 0\n0002 JUMP 3\n0003 HALT\n"
    assert disassemble(Program([], [], [])) == ""


def test_cli_run(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    source = _source(tmp_path, "let x = 5; print x; print 8 / 2;")
    assert main(["run", str(source), "--optimize", "--step-limit", "100"]) == 0
    captured = capsys.readouterr()
    assert captured.out == "5\n4.0\n"
    assert captured.err == ""


def test_cli_build_exec_and_disasm(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    source = _source(tmp_path, "print 1 + 2 * 3;")
    binary = tmp_path / "program.mvm"
    assert main(["build", str(source), str(binary), "--optimize"]) == 0
    assert capsys.readouterr().out == ""
    assert len(loads(binary.read_bytes()).instructions) == 3
    assert main(["exec", str(binary), "--step-limit", "3"]) == 0
    assert capsys.readouterr().out == "7\n"
    assert main(["disasm", str(binary)]) == 0
    assert capsys.readouterr().out == "0000 CONST 0  ; 7\n0001 PRINT\n0002 HALT\n"


@pytest.mark.parametrize("args", [[], ["unknown"], ["run"], ["build", "x"], ["disasm"]])
def test_cli_usage_errors(args: list[str], capsys: pytest.CaptureFixture[str]) -> None:
    assert main(args) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err


@pytest.mark.parametrize("limit", ["0", "-1", "true", "1.0", "no"])
def test_cli_invalid_step_limit(limit: str, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["run", "unused.mv", "--step-limit", limit]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "positive integer" in captured.err


@pytest.mark.parametrize("command", ["run", "exec", "disasm"])
def test_cli_unreadable_file(command: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main([command, str(tmp_path / "missing")]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err


def test_cli_bad_source_encoding(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    source = tmp_path / "invalid.mv"
    source.write_bytes(b"\xff")
    assert main(["run", str(source)]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err


@pytest.mark.parametrize("source", ["print @;", "print ;", "print missing;"])
def test_cli_language_errors(source: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = _source(tmp_path, source)
    assert main(["run", str(path)]) == 3
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err


def test_cli_runtime_output_is_buffered(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    source = _source(tmp_path, 'print "must not leak"; print 1 / 0;')
    assert main(["run", str(source)]) == 3
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "zero" in captured.err


def test_cli_exec_failure_is_buffered(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    binary = tmp_path / "bad.mvm"
    binary.write_bytes(dumps(compile_source("print 1; print true and 5;")))
    assert main(["exec", str(binary)]) == 3
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "BOOL" in captured.err


def test_cli_step_limit_error(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    source = _source(tmp_path, "print 1; while (true) {}")
    assert main(["run", str(source), "--step-limit", "10"]) == 3
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Step limit" in captured.err


def test_cli_corrupt_binary(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    binary = tmp_path / "bad.mvm"
    binary.write_bytes(b"not bytecode")
    for command in ("exec", "disasm"):
        assert main([command, str(binary)]) == 3
        captured = capsys.readouterr()
        assert captured.out == ""
        assert captured.err


def test_cli_build_serialization_error(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    source = _source(tmp_path, f"print {1 << 63};")
    binary = tmp_path / "program.mvm"
    assert main(["build", str(source), str(binary)]) == 3
    assert not binary.exists()
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "64-bit" in captured.err


def test_cli_unwritable_output(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    source = _source(tmp_path, "print 1;")
    assert main(["build", str(source), str(tmp_path)]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err


def test_cli_module_entrypoint(tmp_path: Path) -> None:
    source = _source(tmp_path, "print 5; print 8 / 2;")
    command = [sys.executable, "-B", "-m", "microvm"]
    result = subprocess.run(command + ["run", str(source)], capture_output=True, text=True)
    assert (result.returncode, result.stdout, result.stderr) == (0, "5\n4.0\n", "")
    result = subprocess.run(command + ["nope"], capture_output=True, text=True)
    assert result.returncode == 2 and result.stdout == "" and result.stderr
    source.write_text("print 1; print 1 / 0;", encoding="utf-8")
    result = subprocess.run(command + ["run", str(source)], capture_output=True, text=True)
    assert result.returncode == 3 and result.stdout == "" and result.stderr


def test_public_function_annotations() -> None:
    for name in microvm.__all__:
        value = getattr(microvm, name)
        if inspect.isfunction(value):
            signature = inspect.signature(value)
            assert signature.return_annotation is not inspect.Signature.empty
            assert all(p.annotation is not inspect.Parameter.empty for p in signature.parameters.values())
    signature = inspect.signature(main)
    assert signature.return_annotation is not inspect.Signature.empty
    for cls in (Token, Instr, Program, LexError, ParseError):
        signature = inspect.signature(cls)
        assert all(p.annotation is not inspect.Parameter.empty for p in signature.parameters.values())


def _function_lengths(source: str) -> list[tuple[int, int]]:
    tokens = list(python_tokenize.generate_tokens(io.StringIO(source).readline))
    lengths: list[tuple[int, int]] = []
    for index, token in enumerate(tokens):
        if token.type != python_tokenize.NAME or token.string != "def":
            continue
        body_index = index + 1
        while tokens[body_index].type != python_tokenize.INDENT:
            body_index += 1
        start = tokens[body_index].start[0]
        depth = 1
        end = start
        for inner in tokens[body_index + 1:]:
            if inner.type == python_tokenize.INDENT:
                depth += 1
            elif inner.type == python_tokenize.DEDENT:
                depth -= 1
                if depth == 0:
                    break
            if inner.type not in (python_tokenize.NL, python_tokenize.NEWLINE, python_tokenize.DEDENT):
                end = inner.end[0]
        lengths.append((token.start[0], end - start + 1))
    return lengths


def test_function_bodies_at_most_sixty_lines() -> None:
    root = Path(__file__).resolve().parent.parent
    paths = sorted((root / "microvm").glob("*.py")) + [Path(__file__)]
    for path in paths:
        for line, length in _function_lengths(path.read_text(encoding="utf-8")):
            assert length <= 60, f"{path.name}:{line} has {length} body lines"


def test_at_least_forty_five_test_functions() -> None:
    module = sys.modules[__name__]
    tests = [name for name, value in inspect.getmembers(module, inspect.isfunction) if name.startswith("test_")]
    assert len(tests) >= 45


def test_no_forbidden_imports_or_calls() -> None:
    root = Path(__file__).resolve().parent.parent / "microvm"
    forbidden = {"ast", "compile", "eval", "exec", "dis", "marshal", "pickle", "ctypes"}
    for path in root.glob("*.py"):
        tokens = list(python_tokenize.generate_tokens(io.StringIO(path.read_text(encoding="utf-8")).readline))
        for index, token in enumerate(tokens):
            if token.type == python_tokenize.NAME and token.string in forbidden:
                assert token.string == "compile" and tokens[index - 1].string == "."


def test_all_deliverable_modules_import() -> None:
    for name in (
        "errors", "opcodes", "lexer", "parser", "compiler", "optimizer",
        "vm", "serializer", "disassembler", "__main__",
    ):
        assert importlib.import_module(f"microvm.{name}") is not None
