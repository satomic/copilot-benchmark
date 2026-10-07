from pathlib import Path
import os
import re
import struct
import subprocess
import sys
import zlib

import pytest

import microvm
from microvm import (
    CompileError, Instr, LexError, MicroVMError, OPCODE_NUMBERS, OPCODES,
    ParseError, Program, SerializationError, Token, VMRuntimeError,
    compile_source, disassemble, dumps, execute, fold_constants, loads, parse, tokenize,
)
from microvm.__main__ import main
from microvm.errors import StepLimitError


def run_source(source: str, optimize: bool = False) -> list[str]:
    return execute(compile_source(source, optimize=optimize))


def rechecksum(data: bytes) -> bytes:
    return data[:-4] + struct.pack(">I", zlib.crc32(data[4:-4]))


def change_byte(data: bytes, offset: int, value: int) -> bytes:
    changed = bytearray(data)
    changed[offset] = value
    return rechecksum(bytes(changed))


def invoke_cli(*arguments: str) -> subprocess.CompletedProcess[str]:
    environment = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    return subprocess.run(
        [sys.executable, "-m", "microvm", *arguments],
        capture_output=True, text=True, encoding="utf-8", env=environment,
        check=False, timeout=10,
    )


def test_exports() -> None:
    expected = (
        "tokenize Token parse compile_source Program Instr fold_constants execute "
        "dumps loads disassemble OPCODES OPCODE_NUMBERS MicroVMError LexError "
        "ParseError CompileError SerializationError VMRuntimeError"
    ).split()
    assert microvm.__all__ == expected
    assert len(microvm.__all__) == 19
    assert all(hasattr(microvm, name) for name in expected)


def test_error_hierarchy() -> None:
    for error in (LexError, ParseError, CompileError, SerializationError, VMRuntimeError):
        assert issubclass(error, MicroVMError)
    assert issubclass(StepLimitError, VMRuntimeError)
    assert LexError("bad", 3).offset == 3
    assert ParseError("bad", 4).offset == 4


def test_opcode_numbers() -> None:
    assert OPCODES == (
        "CONST", "LOAD", "STORE", "ADD", "SUB", "MUL", "DIV", "MOD", "NEG", "NOT",
        "EQ", "NE", "LT", "LE", "GT", "GE", "JUMP", "JUMP_IF_FALSE", "PRINT", "POP", "HALT",
    )
    assert OPCODE_NUMBERS == {name: index + 1 for index, name in enumerate(OPCODES)}


def test_lexer_tokens_and_offsets() -> None:
    assert tokenize("let x = 12;") == [
        Token("KEYWORD", "let", "let", 0), Token("IDENT", "x", "x", 4),
        Token("OP", "=", "=", 6), Token("INT", "12", 12, 8),
        Token("OP", ";", ";", 10),
    ]


def test_lexer_empty_and_comments() -> None:
    assert tokenize(" \t\r\n// hi") == []
    assert tokenize("// first\nprint// second\n1;")[-2].value == 1
    assert run_source("print 1;// no final newline") == ["1"]
    assert run_source("// first\rprint 1;// second\r\nprint 2;") == ["1", "2"]


def test_lexer_keyword_case_and_identifiers() -> None:
    tokens = tokenize("let print if else while true false and or not IF _x a09")
    assert [token.kind for token in tokens] == ["KEYWORD"] * 10 + ["IDENT"] * 3
    assert run_source("let IF = 2; print IF;") == ["2"]


def test_lexer_floats() -> None:
    assert [token.value for token in tokenize("1.5e3 2.0E-2 0.0 123")] == [
        1500.0, 0.02, 0.0, 123,
    ]


@pytest.mark.parametrize("source", ["1.", ".5", "1e2", "1.0e", "1.0e+", "1.0.2"])
def test_lexer_bad_numbers(source: str) -> None:
    with pytest.raises(LexError) as caught:
        tokenize(source)
    assert 0 <= caught.value.offset < len(source)


def test_lexer_decodes_strings() -> None:
    value = 'a\n\t"\\z'
    assert tokenize(r'"a\n\t\"\\z"') == [Token("STRING", value, value, 0)]
    assert tokenize('"// text"')[0].value == "// text"
    assert tokenize('""')[0].value == ""


@pytest.mark.parametrize("source", ['"abc', '"x\\', r'"\r"', r'"\0"', '"a\nb"', '"a\rb"'])
def test_lexer_bad_strings(source: str) -> None:
    with pytest.raises(LexError) as caught:
        tokenize(source)
    assert isinstance(caught.value.offset, int)


def test_lexer_operators_longest_match() -> None:
    operators = "+ - * / % ( ) { } ; = == != < <= > >="
    assert [token.text for token in tokenize(operators)] == operators.split()


@pytest.mark.parametrize("source,offset", [("@", 0), ("print !;", 6), ("print é;", 6)])
def test_lexer_unexpected_character(source: str, offset: int) -> None:
    with pytest.raises(LexError) as caught:
        tokenize(source)
    assert caught.value.offset == offset


def test_parser_accepts_all_statements() -> None:
    source = """
        let x = 3; { x = x - 1; print x; }
        if (x > 5) { print "big"; } else if (x > 1) { print "mid"; }
        else { print "small"; }
        while (x > 0) { x = x - 1; } print x;
    """
    assert parse(source) is not None
    assert run_source(source) == ["2", "mid", "0"]


def test_parser_empty_program_and_blocks() -> None:
    assert run_source("") == []
    assert run_source("{} {{}}") == []


@pytest.mark.parametrize("source", [
    "let x;", "let x = ;", "print 1", "x 1;", "print ;", "else {}",
    "{ print 1;", "if true {}", "while (true) print 1;", "if (true) {} else print 1;",
    "print (1;", "print +1;", "let true = 1;", "let IF = 1; IF;",
])
def test_parser_malformed_programs(source: str) -> None:
    with pytest.raises(ParseError) as caught:
        parse(source)
    assert 0 <= caught.value.offset <= len(source)


def test_parser_offsets() -> None:
    with pytest.raises(ParseError) as caught:
        parse("print ;")
    assert caught.value.offset == 6
    with pytest.raises(ParseError) as caught:
        parse("print 1")
    assert caught.value.offset == 7


def test_parser_lex_errors_pass_through() -> None:
    with pytest.raises(LexError) as caught:
        parse("print @;")
    assert caught.value.offset == 6


@pytest.mark.parametrize("source", ["print 1 < 2 < 3;", "print 1 == 2 != 3;"])
def test_comparison_nonassociative(source: str) -> None:
    with pytest.raises(ParseError):
        parse(source)
    assert run_source("print (1 < 2) == true;") == ["true"]


def test_expression_precedence() -> None:
    source = """
        print 1 + 2 * 3; print 8 / 2 + 1;
        print not 1 < 2; print true or false and false;
        print -2 * -3 + 1; print 10 - 3 - 2;
    """
    assert run_source(source) == ["7", "5.0", "false", "true", "7", "5"]


def test_numbers_and_result_types() -> None:
    assert run_source("print 1+2; print 3-1; print 2*4; print 1+2.0;") == [
        "3", "2", "8", "3.0",
    ]
    assert run_source("print 3.0-1; print 2*4.0; print 7/2; print 4/2;") == [
        "2.0", "8.0", "3.5", "2.0",
    ]


def test_modulo_sign_and_unary_minus() -> None:
    assert run_source("print -7%3; print 7%-3; print --2; print -1.5;") == [
        "2", "-2", "2", "-1.5",
    ]


def test_string_concatenation_and_rendering() -> None:
    assert run_source(r'print "a"+"b"; print "x\n\t\"\\y"; print "";') == [
        "ab", 'x\n\t"\\y', "",
    ]
    assert run_source("print true; print false;") == ["true", "false"]


@pytest.mark.parametrize("expression", [
    "true + 1", "1 - false", "true * true", "true / 1", "true % 1",
    '"a" + 1', '"a" - "b"', '"a" * 2', "1.0 % 2", "2 % 1.0",
    '-true', '-"a"',
])
def test_arithmetic_type_errors(expression: str) -> None:
    for optimize in (False, True):
        with pytest.raises(VMRuntimeError):
            run_source(f"print {expression};", optimize)


@pytest.mark.parametrize("expression", ["1/0", "1/0.0", "1%0", "1/-0.0"])
def test_division_and_modulo_zero(expression: str) -> None:
    for optimize in (False, True):
        with pytest.raises(VMRuntimeError):
            run_source(f"print {expression};", optimize)


def test_equality_cross_types() -> None:
    assert run_source("""
        print true == 1; print false == 0; print 1 == 1.0;
        print "1" == 1; print "a" != true; print true != 1;
        print true == true; print "a" == "a";
    """) == ["false", "false", "true", "false", "true", "true", "true", "true"]


def test_ordering_numbers_and_strings() -> None:
    assert run_source("""
        print 1 < 2.0; print 2 <= 2.0; print 3.0 > 2; print 2.0 >= 2;
        print "a" < "b"; print "aa" <= "ab"; print "Z" > "A"; print "z" >= "z";
    """) == ["true"] * 8


@pytest.mark.parametrize("expression", [
    "true < false", "false <= 1", "1 > true", '"a" >= 1', '1 < "a"',
])
def test_ordering_type_errors(expression: str) -> None:
    for optimize in (False, True):
        with pytest.raises(VMRuntimeError):
            run_source(f"print {expression};", optimize)


def test_boolean_truth_tables() -> None:
    for optimize in (False, True):
        assert run_source("""
            print false and false; print false and true;
            print true and false; print true and true;
            print false or false; print false or true;
            print true or false; print true or true;
            print not true; print not false; print not not true;
        """, optimize) == [
            "false", "false", "false", "true", "false", "true",
            "true", "true", "false", "true", "true",
        ]


@pytest.mark.parametrize("expression", [
    "1 and false", "1 or true", "true and 5", "false or 5", "not 1",
    '"x" and false', 'false or ""',
])
def test_boolean_strict_types(expression: str) -> None:
    for optimize in (False, True):
        with pytest.raises(VMRuntimeError):
            run_source(f"let y = {expression};", optimize)


def test_short_circuit_skips_failing_rhs() -> None:
    for optimize in (False, True):
        assert run_source("""
            print false and (1/0 == 0); print true or (1/0 == 0);
            print false and 5; print true or "x";
        """, optimize) == ["false", "true", "false", "true"]


def test_short_circuit_skips_unassigned_rhs() -> None:
    for optimize in (False, True):
        assert run_source("""
            if (false) { let y = true; }
            print false and y; print true or y;
        """, optimize) == ["false", "true"]


def test_logic_evaluated_rhs_raises() -> None:
    for source in ("print true and (1/0 == 0);", "print false or (1/0 == 0);"):
        for optimize in (False, True):
            with pytest.raises(VMRuntimeError):
                run_source(source, optimize)


def test_logic_compiles_jumps_and_checks_rhs() -> None:
    for op in ("and", "or"):
        program = compile_source(f"print true {op} false;")
        assert "JUMP" in [instruction.op for instruction in program.instructions]
        assert "JUMP_IF_FALSE" in [instruction.op for instruction in program.instructions]
    assert run_source("let a=true; let b=false; print (a and b) or a;") == ["true"]


@pytest.mark.parametrize("source", ['if (1) {}', 'while ("x") {}', 'if (false) {} else if (5) {}'])
def test_conditions_require_bool(source: str) -> None:
    for optimize in (False, True):
        with pytest.raises(VMRuntimeError):
            run_source(source, optimize)


def test_if_and_else_if_branches() -> None:
    assert run_source("""
        let x = 3;
        if (x > 5) { print "big"; } else if (x > 2) { print "mid"; }
        else { print "small"; }
        if (true) { print 1; } else { print 1/0; }
        if (false) { print 1/0; }
    """) == ["mid", "1"]


def test_while_assignment_and_nested_blocks() -> None:
    assert run_source("""
        let x=3; let total=0;
        while (x > 0) { {total = total+x;} x=x-1; }
        print total; print x;
    """) == ["6", "0"]


def test_blocks_have_global_namespace() -> None:
    program = compile_source("{ let a=1; } if (true) { let b=2; } print a+b;")
    assert program.names == ["a", "b"]
    assert execute(program) == ["3"]


@pytest.mark.parametrize("source", [
    "let x=1; let x=2;", "let x=1; if (false) {let x=2;}",
    "if (true) {let x=1;} else {let x=2;}",
])
def test_duplicate_declarations(source: str) -> None:
    for optimize in (False, True):
        with pytest.raises(CompileError):
            compile_source(source, optimize=optimize)


@pytest.mark.parametrize("source", [
    "x=1;", "print x;", "print false and x;", "if (false) { x=1; }",
])
def test_undeclared_names_checked_before_folding(source: str) -> None:
    for optimize in (False, True):
        with pytest.raises(CompileError):
            compile_source(source, optimize=optimize)


def test_unassigned_variable_names_error() -> None:
    for optimize in (False, True):
        with pytest.raises(VMRuntimeError, match="missing"):
            run_source("if (false) {let missing=1;} print missing;", optimize)
        with pytest.raises(VMRuntimeError, match="x"):
            run_source("let x=x;", optimize)


def test_forward_global_declarations() -> None:
    assert run_source("x=2; print x; let x=3; print x;") == ["2", "3"]
    with pytest.raises(VMRuntimeError, match="x"):
        run_source("print x; let x=1;")
    assert run_source("if (false) {let x=1;} x=2; print x;") == ["2"]


def test_constant_pool_deduplication_by_type() -> None:
    program = compile_source("print 1; print 1.0; print true; print 1; print 1.0; print true;")
    assert [type(value) for value in program.constants] == [int, float, bool]
    assert [instruction.arg for instruction in program.instructions if instruction.op == "CONST"] == [
        0, 1, 2, 0, 1, 2,
    ]
    assert execute(program) == ["1", "1.0", "true", "1", "1.0", "true"]


def test_literal_instruction_shape_and_final_halt() -> None:
    assert compile_source("print 1;").instructions == [
        Instr("CONST", 0), Instr("PRINT", None), Instr("HALT", None),
    ]
    for source in ("", "{}", "if (true) {} else {}", "while (false) {}", "print true and false;"):
        program = compile_source(source)
        assert program.instructions[-1] == Instr("HALT")
        assert sum(instruction.op == "HALT" for instruction in program.instructions) == 1
        for instruction in program.instructions:
            takes_arg = instruction.op in ("CONST", "LOAD", "STORE", "JUMP", "JUMP_IF_FALSE")
            assert (instruction.arg is not None) == takes_arg


def test_recursive_constant_folding_shape() -> None:
    source = "print 1 + 2 * 3;"
    optimized = compile_source(source, optimize=True)
    assert optimized.constants == [7]
    assert optimized.instructions == [Instr("CONST", 0), Instr("PRINT"), Instr("HALT")]
    assert len(compile_source(source).instructions) > 3


@pytest.mark.parametrize("expression,expected", [
    ("-(1+2)", "-3"), ("7/2", "3.5"), ("-7%3", "2"), ('"a"+"b"', "ab"),
    ("1==1.0", "true"), ("true==1", "false"), ('"a"<"b"', "true"),
    ("not false", "true"), ("true and false", "false"), ("false or true", "true"),
])
def test_successful_constant_folding(expression: str, expected: str) -> None:
    program = compile_source(f"print {expression};", optimize=True)
    assert len(program.instructions) == 3
    assert execute(program) == [expected]


def test_fold_errors_remain_runtime_errors() -> None:
    for expression in ("1/0", '"a"+1', "true and 5", "false or 5", "not 5"):
        program = compile_source(f"let y={expression};", optimize=True)
        with pytest.raises(VMRuntimeError):
            execute(program)
    assert run_source("if (false) {print 1/0;}", True) == []


def test_fold_short_circuit_any_rhs() -> None:
    for expression, expected in (("false and (1/0)", "false"), ("true or 5", "true")):
        program = compile_source(f"print {expression};", optimize=True)
        assert len(program.instructions) == 3
        assert execute(program) == [expected]


def test_fold_constants_public_ast_interface() -> None:
    root = parse("print 1+2;")
    result = fold_constants(root)
    assert root != result
    assert fold_constants(result) == result
    with pytest.raises(TypeError):
        fold_constants(None)


def test_optimization_preserves_variable_reads() -> None:
    source = "let x=2; print x+3; x=4; print x+3;"
    assert run_source(source) == run_source(source, True) == ["5", "7"]


def test_optimization_preserves_signed_zero() -> None:
    source = "print 0.0; print -0.0; print -(-0.0);"
    assert run_source(source) == run_source(source, True) == ["0.0", "-0.0", "0.0"]


@pytest.mark.parametrize("limit", [0, -1, True, False, 1.5, "10", None])
def test_invalid_step_limits(limit: object) -> None:
    with pytest.raises(ValueError):
        execute(compile_source(""), step_limit=limit)  # type: ignore[arg-type]


def test_step_limit_exact_boundary() -> None:
    program = compile_source("print 1;")
    assert execute(program, step_limit=3) == ["1"]
    with pytest.raises(StepLimitError):
        execute(program, step_limit=2)
    assert execute(compile_source(""), step_limit=1) == []


def test_step_limit_infinite_loop() -> None:
    for optimize in (False, True):
        with pytest.raises(StepLimitError):
            execute(compile_source("while (true) {}", optimize=optimize), step_limit=20)


def test_vm_pop_and_jump() -> None:
    program = Program([1, 2], [], [
        Instr("CONST", 0), Instr("POP"), Instr("JUMP", 4),
        Instr("CONST", 0), Instr("CONST", 1), Instr("PRINT"), Instr("HALT"),
    ])
    assert execute(program) == ["2"]


@pytest.mark.parametrize("instructions", [
    [Instr("PRINT"), Instr("HALT")], [Instr("JUMP", 10), Instr("HALT")],
    [Instr("CONST", 0), Instr("HALT")], [Instr("BOGUS"), Instr("HALT")],
    [Instr("HALT", 0)], [Instr("CONST"), Instr("HALT")], [Instr("POP"), Instr("HALT")],
])
def test_vm_invalid_bytecode_is_explicit(instructions: list[Instr]) -> None:
    with pytest.raises(VMRuntimeError):
        execute(Program([], [], instructions))


def test_serializer_round_trip_and_determinism() -> None:
    source = """
        let x=2; while (x>0) {print x; x=x-1;}
        print 1.25; print "héllo"; print true; print false;
        print true and (x==0); print false or (x==0);
    """
    for optimize in (False, True):
        program = compile_source(source, optimize=optimize)
        encoded = dumps(program)
        decoded = loads(encoded)
        assert decoded == program
        assert encoded == dumps(program) == dumps(decoded)
        assert execute(decoded) == execute(program)


def test_serializer_exact_binary_layout() -> None:
    body = (
        b"\x01" + struct.pack(">HH", 0, 1) + b"\x01" + struct.pack(">q", 1)
        + struct.pack(">I", 3) + struct.pack(">BI", 1, 0)
        + struct.pack(">BI", 19, 0xFFFFFFFF) + struct.pack(">BI", 21, 0xFFFFFFFF)
    )
    expected = b"MVM1" + body + struct.pack(">I", zlib.crc32(body))
    assert dumps(compile_source("print 1;")) == expected
    assert execute(loads(expected)) == ["1"]


def test_serializer_all_constant_tags_and_unicode() -> None:
    program = Program(
        [-(2**63), 2**63-1, 2.5, "雪\n\t", False, True], ["雪"],
        [Instr("HALT")],
    )
    decoded = loads(dumps(program))
    assert decoded == program
    assert [type(value) for value in decoded.constants] == [int, int, float, str, bool, bool]


@pytest.mark.parametrize("value", [-(2**63)-1, 2**63])
def test_serializer_int_out_of_range(value: int) -> None:
    program = Program([value], [], [Instr("HALT")])
    with pytest.raises(SerializationError):
        dumps(program)


def test_serializer_bad_magic() -> None:
    data = dumps(compile_source("print 1;"))
    with pytest.raises(SerializationError, match="magic"):
        loads(b"BAD!" + data[4:])


def test_serializer_unsupported_version() -> None:
    data = dumps(compile_source(""))
    with pytest.raises(SerializationError, match="version"):
        loads(change_byte(data, 4, 2))


def test_serializer_checksum_mismatch() -> None:
    data = bytearray(dumps(compile_source("print 1;")))
    data[17] ^= 1
    with pytest.raises(SerializationError, match="Checksum"):
        loads(bytes(data))


def test_serializer_checks_checksum_before_lengths() -> None:
    data = bytearray(dumps(compile_source("")))
    data[5:7] = b"\xff\xff"
    with pytest.raises(SerializationError, match="Checksum"):
        loads(bytes(data))


def test_serializer_unknown_constant_tag() -> None:
    data = dumps(compile_source("print 1;"))
    with pytest.raises(SerializationError, match="constant tag"):
        loads(change_byte(data, 9, 99))


def test_serializer_unknown_opcode() -> None:
    data = dumps(compile_source(""))
    with pytest.raises(SerializationError, match="opcode"):
        loads(change_byte(data, 13, 99))


def test_serializer_invalid_bool_payload() -> None:
    data = dumps(compile_source("print true;"))
    with pytest.raises(SerializationError, match="BOOL"):
        loads(change_byte(data, 10, 2))


def test_serializer_every_truncation() -> None:
    data = dumps(compile_source('let x="héllo"; print x;'))
    for end in range(len(data)):
        with pytest.raises(SerializationError):
            loads(data[:end])


def test_serializer_truncated_with_valid_checksum() -> None:
    data = dumps(compile_source('print "abc";'))
    for end in range(5, len(data)-4):
        body = data[4:end]
        truncated = b"MVM1" + body + struct.pack(">I", zlib.crc32(body))
        with pytest.raises(SerializationError):
            loads(truncated)


def test_serializer_trailing_bytes() -> None:
    data = dumps(compile_source(""))
    with pytest.raises(SerializationError):
        loads(data + b"\x00")
    extra_body = data[:-4] + b"\x00" + data[-4:]
    with pytest.raises(SerializationError, match="Trailing"):
        loads(rechecksum(extra_body))


def test_serializer_invalid_utf8() -> None:
    data = dumps(compile_source('print "a";'))
    with pytest.raises(SerializationError, match="UTF-8"):
        loads(change_byte(data, 14, 255))
    data = dumps(compile_source("let x=1;"))
    with pytest.raises(SerializationError, match="UTF-8"):
        loads(change_byte(data, 9, 255))


def test_serializer_argument_sentinel_validation() -> None:
    data = dumps(compile_source("print 1;"))
    changed = data[:23] + b"\xff\xff\xff\xff" + data[27:]
    with pytest.raises(SerializationError, match="requires an argument"):
        loads(rechecksum(changed))
    data = dumps(compile_source(""))
    changed = data[:14] + b"\x00\x00\x00\x00" + data[18:]
    with pytest.raises(SerializationError, match="takes no argument"):
        loads(rechecksum(changed))


def test_serializer_invalid_lengths() -> None:
    data = dumps(compile_source('print "a";'))
    changed = data[:10] + b"\xff\xff\xff\xff" + data[14:]
    with pytest.raises(SerializationError, match="Truncated"):
        loads(rechecksum(changed))
    data = dumps(compile_source(""))
    changed = data[:9] + b"\xff\xff\xff\xff" + data[13:]
    with pytest.raises(SerializationError, match="Truncated"):
        loads(rechecksum(changed))


@pytest.mark.parametrize("program", [
    Program([], [], []), Program([], [], [Instr("HALT"), Instr("HALT")]),
    Program([], [], [Instr("UNKNOWN"), Instr("HALT")]),
    Program([], [], [Instr("PRINT", 0), Instr("HALT")]),
    Program([], [], [Instr("JUMP"), Instr("HALT")]),
    Program([], [], [Instr("JUMP", 0xFFFFFFFF), Instr("HALT")]),
    Program([], [], [Instr("CONST", 0), Instr("HALT")]),
    Program([], [], [Instr("LOAD", 0), Instr("HALT")]),
])
def test_serializer_rejects_invalid_program(program: Program) -> None:
    with pytest.raises(SerializationError):
        dumps(program)


def test_serializer_rejects_unencodable_text() -> None:
    with pytest.raises(SerializationError):
        dumps(Program(["\ud800"], [], [Instr("HALT")]))
    with pytest.raises(SerializationError):
        dumps(Program([], ["a"*65536], [Instr("HALT")]))


def test_disassembly_exact() -> None:
    assert disassemble(compile_source("print 1;")) == (
        "0000 CONST 0  ; 1\n0001 PRINT\n0002 HALT\n"
    )


def test_disassembly_string_escapes() -> None:
    program = compile_source(r'print "a\n\t\"\\b";')
    assert disassemble(program) == (
        '0000 CONST 0  ; "a\\n\\t\\"\\\\b"\n0001 PRINT\n0002 HALT\n'
    )


def test_disassembly_boolean_and_float() -> None:
    assert disassemble(compile_source("print true; print 1.0; print false;")) == (
        "0000 CONST 0  ; true\n0001 PRINT\n0002 CONST 1  ; 1.0\n"
        "0003 PRINT\n0004 CONST 2  ; false\n0005 PRINT\n0006 HALT\n"
    )


def test_disassembly_other_arguments() -> None:
    program = compile_source("let x=1; print x; while (false) {}")
    lines = disassemble(program).splitlines()
    assert lines[1] == "0001 STORE 0"
    assert lines[2] == "0002 LOAD 0"
    assert any("JUMP_IF_FALSE" in line for line in lines)
    assert disassemble(program).endswith("\n")
    assert len(lines) == len(program.instructions)


def test_cli_run_success(tmp_path: Path) -> None:
    source = tmp_path / "source.mv"
    source.write_text("let x = 5; print x; print 8 / 2;", encoding="utf-8")
    result = invoke_cli("run", str(source))
    assert (result.returncode, result.stdout, result.stderr) == (0, "5\n4.0\n", "")
    result = invoke_cli("run", str(source), "--optimize", "--step-limit", "100")
    assert (result.returncode, result.stdout, result.stderr) == (0, "5\n4.0\n", "")


def test_cli_build_exec_disasm(tmp_path: Path) -> None:
    source = tmp_path / "source.mv"
    binary = tmp_path / "program.mvm"
    source.write_text("print 1+2*3;", encoding="utf-8")
    result = invoke_cli("build", str(source), str(binary), "--optimize")
    assert (result.returncode, result.stdout, result.stderr) == (0, "", "")
    assert execute(loads(binary.read_bytes())) == ["7"]
    result = invoke_cli("exec", str(binary), "--step-limit", "3")
    assert (result.returncode, result.stdout, result.stderr) == (0, "7\n", "")
    result = invoke_cli("disasm", str(binary))
    assert (result.returncode, result.stdout, result.stderr) == (
        0, "0000 CONST 0  ; 7\n0001 PRINT\n0002 HALT\n", "",
    )


@pytest.mark.parametrize("arguments", [
    (), ("unknown",), ("run",), ("build", "file"),
    ("run", "file", "--step-limit", "0"), ("exec", "file", "--step-limit", "-1"),
    ("run", "file", "--step-limit", "1.5"), ("run", "file", "--step-limit", "abc"),
])
def test_cli_usage_errors(arguments: tuple[str, ...]) -> None:
    result = invoke_cli(*arguments)
    assert result.returncode == 2
    assert result.stdout == ""
    assert result.stderr


def test_cli_unreadable_file(tmp_path: Path) -> None:
    for command in ("run", "exec", "disasm"):
        result = invoke_cli(command, str(tmp_path / "missing"))
        assert result.returncode == 2
        assert result.stdout == ""
        assert result.stderr


@pytest.mark.parametrize("source", [
    "print @;", "print ;", "print x;", "print 1; print 1/0;",
    "print 1; print true and 5;", "print 1; while (true) {}",
])
def test_cli_microvm_errors_are_buffered(tmp_path: Path, source: str) -> None:
    path = tmp_path / "source.mv"
    path.write_text(source, encoding="utf-8")
    result = invoke_cli("run", str(path), "--step-limit", "20", "--optimize")
    assert result.returncode == 3
    assert result.stdout == ""
    assert result.stderr


def test_cli_binary_runtime_error_is_buffered(tmp_path: Path) -> None:
    path = tmp_path / "program.mvm"
    path.write_bytes(dumps(compile_source("print 1; print 1/0;")))
    result = invoke_cli("exec", str(path))
    assert result.returncode == 3
    assert result.stdout == ""
    assert result.stderr


def test_cli_malformed_binary(tmp_path: Path) -> None:
    path = tmp_path / "bad.mvm"
    path.write_bytes(b"not bytecode")
    for command in ("exec", "disasm"):
        result = invoke_cli(command, str(path))
        assert result.returncode == 3
        assert result.stdout == ""
        assert result.stderr


def test_cli_build_write_failure(tmp_path: Path) -> None:
    path = tmp_path / "source.mv"
    path.write_text("print 1;", encoding="utf-8")
    result = invoke_cli("build", str(path), str(tmp_path / "missing" / "out.mvm"))
    assert result.returncode == 2
    assert result.stdout == ""
    assert result.stderr


def test_cli_main_returns_codes(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = tmp_path / "source.mv"
    path.write_text("print 1;", encoding="utf-8")
    assert main(["run", str(path)]) == 0
    assert capsys.readouterr().out == "1\n"
    assert main(["unknown"]) == 2
    captured = capsys.readouterr()
    assert captured.out == "" and captured.err
    path.write_text("print 1/0;", encoding="utf-8")
    assert main(["run", str(path)]) == 3
    captured = capsys.readouterr()
    assert captured.out == "" and captured.err


def test_deliverable_function_bodies_are_short_and_annotated() -> None:
    root = Path(__file__).resolve().parents[1]
    paths = list((root / "microvm").glob("*.py")) + [Path(__file__)]
    function_count = 0
    test_count = 0
    for path in paths:
        lines = path.read_text(encoding="utf-8").splitlines()
        for index, line in enumerate(lines):
            if not re.match(r"\s*def \w+\(", line):
                continue
            function_count += 1
            test_count += line.startswith("def test_")
            indentation = len(line) - len(line.lstrip())
            signature_end = index
            while not lines[signature_end].rstrip().endswith(":"):
                signature_end += 1
            assert " -> " in " ".join(lines[index:signature_end+1]), (path, line)
            body_end = signature_end + 1
            while body_end < len(lines):
                current = lines[body_end]
                if current.strip() and len(current)-len(current.lstrip()) <= indentation:
                    break
                body_end += 1
            assert body_end-signature_end-1 <= 60, (path, line)
    assert function_count > 45
    assert test_count >= 45
