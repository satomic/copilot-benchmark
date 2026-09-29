import struct
import subprocess
import sys
import zlib

import pytest

import microvm
from microvm import (
    CompileError,
    LexError,
    ParseError,
    SerializationError,
    VMRuntimeError,
    compile_source,
    disassemble,
    dumps,
    execute,
    loads,
    tokenize,
)
from microvm.compiler import Instr, Program
from microvm.errors import StepLimitError


def run(source: str, optimize: bool = False) -> list[str]:
    return execute(compile_source(source, optimize=optimize))


def fixed_checksum(data: bytes) -> bytes:
    return data[:-4] + struct.pack(">I", zlib.crc32(data[4:-4]) & 0xFFFFFFFF)


def test_tokenize_integer() -> None:
    assert tokenize("12")[0].value == 12


def test_tokenize_float_exponent() -> None:
    assert tokenize("1.5e2")[0].value == 150.0


def test_tokenize_decoded_string() -> None:
    token = tokenize(r'"a\n\t\"\\b"')[0]
    assert token.text == 'a\n\t"\\b'


def test_tokenize_keywords_case_sensitive() -> None:
    tokens = tokenize("if IF")
    assert [token.kind for token in tokens] == ["KEYWORD", "IDENT"]


def test_tokenize_comment() -> None:
    assert [token.value for token in tokenize("1 // x\n 2")] == [1, 2]


def test_lex_rejects_dot_five() -> None:
    with pytest.raises(LexError) as error:
        tokenize(".5")
    assert error.value.offset == 0


def test_lex_rejects_one_dot() -> None:
    with pytest.raises(LexError):
        tokenize("1.")


def test_lex_rejects_bad_escape() -> None:
    with pytest.raises(LexError):
        tokenize(r'"\q"')


def test_lex_rejects_unterminated_string() -> None:
    with pytest.raises(LexError):
        tokenize('"abc')


def test_lex_rejects_literal_newline() -> None:
    with pytest.raises(LexError):
        tokenize('"a\nb"')


def test_parse_rejects_chained_comparison() -> None:
    with pytest.raises(ParseError):
        microvm.parse("print 1 < 2 < 3;")


def test_parse_rejects_missing_semicolon() -> None:
    with pytest.raises(ParseError) as error:
        microvm.parse("print 1")
    assert error.value.offset == 7


def test_parse_requires_if_block() -> None:
    with pytest.raises(ParseError):
        microvm.parse("if (true) print 1;")


def test_parse_requires_while_block() -> None:
    with pytest.raises(ParseError):
        microvm.parse("while (true) print 1;")


def test_integer_arithmetic() -> None:
    assert run("print 1 + 2 * 3 - 4;") == ["3"]


def test_float_arithmetic() -> None:
    assert run("print 1 + 2.5; print 4.0 * 2;") == ["3.5", "8.0"]


def test_division_always_float() -> None:
    assert run("print 7 / 2; print 4 / 2;") == ["3.5", "2.0"]


def test_modulo_python_sign_rule() -> None:
    assert run("print -7 % 3;") == ["2"]


def test_string_concatenation() -> None:
    assert run('print "a" + "b";') == ["ab"]


def test_string_number_add_fails() -> None:
    with pytest.raises(VMRuntimeError):
        run('print "a" + 1;')


def test_bool_is_not_number() -> None:
    with pytest.raises(VMRuntimeError):
        run("print true + 1;")


def test_division_by_zero() -> None:
    with pytest.raises(VMRuntimeError):
        run("print 1 / 0;")


def test_modulo_by_zero() -> None:
    with pytest.raises(VMRuntimeError):
        run("print 1 % 0;")


def test_modulo_requires_ints() -> None:
    with pytest.raises(VMRuntimeError):
        run("print 4.0 % 2;")


def test_negation_requires_number() -> None:
    with pytest.raises(VMRuntimeError):
        run("print -true;")


def test_equality_type_rules() -> None:
    assert run("print true == 1; print 1 == 1.0; print 1 != 2;") == [
        "false", "true", "true",
    ]


def test_ordered_numeric_comparison() -> None:
    assert run("print 1 < 1.5; print 2.0 >= 2;") == ["true", "true"]


def test_ordered_string_comparison() -> None:
    assert run('print "aa" < "b";') == ["true"]


def test_ordered_mixed_comparison_fails() -> None:
    with pytest.raises(VMRuntimeError):
        run('print "1" < 2;')


def test_ordered_bool_comparison_fails() -> None:
    with pytest.raises(VMRuntimeError):
        run("print false < true;")


def test_not_boolean() -> None:
    assert run("print not false;") == ["true"]


def test_not_rejects_non_boolean() -> None:
    with pytest.raises(VMRuntimeError):
        run("print not 1;")


def test_and_short_circuits() -> None:
    assert run("print false and (1 / 0 == 0);") == ["false"]


def test_or_short_circuits() -> None:
    assert run("print true or (1 / 0 == 0);") == ["true"]


def test_and_checks_right_boolean() -> None:
    with pytest.raises(VMRuntimeError):
        run("print true and 5;")


def test_or_checks_left_boolean() -> None:
    with pytest.raises(VMRuntimeError):
        run("print 1 or true;")


def test_if_requires_boolean() -> None:
    with pytest.raises(VMRuntimeError):
        run("if (1) { print 1; }")


def test_while_requires_boolean() -> None:
    with pytest.raises(VMRuntimeError):
        run("while (1) {}")


def test_if_else_if() -> None:
    source = 'let x = 3; if (x > 5) { print "big"; } else if (x > 2) { print "mid"; }'
    assert run(source) == ["mid"]


def test_while_loop_and_assignment() -> None:
    assert run("let x = 3; while (x > 0) { print x; x = x - 1; }") == ["3", "2", "1"]


def test_blocks_have_no_scope() -> None:
    assert run("{ let x = 4; } print x;") == ["4"]


def test_duplicate_declaration_fails() -> None:
    with pytest.raises(CompileError):
        compile_source("let x = 1; { let x = 2; }")


def test_undeclared_assignment_fails() -> None:
    with pytest.raises(CompileError):
        compile_source("x = 1;")


def test_undeclared_read_fails() -> None:
    with pytest.raises(CompileError):
        compile_source("print x;")


def test_declaration_applies_to_whole_program() -> None:
    program = compile_source("print x; let x = 1;")
    with pytest.raises(VMRuntimeError, match="x"):
        execute(program)


def test_never_assigned_branch_variable() -> None:
    with pytest.raises(VMRuntimeError, match="x"):
        run("if (false) { let x = 1; } print x;")


def test_print_rendering() -> None:
    assert run('print 2; print 2.0; print true; print "x";') == ["2", "2.0", "true", "x"]


def test_constant_pool_deduplicates_by_type() -> None:
    program = compile_source("print 1; print 1; print 1.0; print true;")
    assert len(program.constants) == 3
    assert [type(value) for value in program.constants] == [int, float, bool]


def test_literal_has_exact_instruction_shape() -> None:
    assert compile_source("print 1;").instructions == [
        Instr("CONST", 0), Instr("PRINT", None), Instr("HALT", None),
    ]


def test_single_final_halt() -> None:
    instructions = compile_source("if (true) { print 1; }").instructions
    assert [item.op for item in instructions].count("HALT") == 1
    assert instructions[-1].op == "HALT"


def test_optimizer_folds_recursive_arithmetic() -> None:
    program = compile_source("print 1 + 2 * 3;", optimize=True)
    assert len(program.instructions) == 3
    assert execute(program) == ["7"]


def test_optimizer_preserves_division_by_zero() -> None:
    with pytest.raises(VMRuntimeError):
        run("print 1 / 0;", optimize=True)


def test_optimizer_preserves_and_type_check() -> None:
    with pytest.raises(VMRuntimeError):
        run("print true and 5;", optimize=True)


def test_optimizer_safe_short_circuit() -> None:
    assert run("print false and (1 / 0 == 0);", optimize=True) == ["false"]


def test_serializer_round_trip() -> None:
    program = compile_source('let x = 3; print x + 0.5;')
    assert execute(loads(dumps(program))) == execute(program)


def test_serializer_is_deterministic() -> None:
    program = compile_source("print 1;")
    assert dumps(program) == dumps(program)


def test_serializer_rejects_large_integer() -> None:
    with pytest.raises(SerializationError):
        dumps(Program([1 << 63], [], [Instr("HALT", None)]))


def test_serializer_rejects_bad_magic() -> None:
    data = bytearray(dumps(compile_source("print 1;")))
    data[0] = 0
    with pytest.raises(SerializationError):
        loads(bytes(data))


def test_serializer_rejects_truncation() -> None:
    with pytest.raises(SerializationError):
        loads(dumps(compile_source("print 1;"))[:-1])


def test_serializer_rejects_checksum_mismatch() -> None:
    data = bytearray(dumps(compile_source("print 1;")))
    data[5] ^= 1
    with pytest.raises(SerializationError):
        loads(bytes(data))


def test_serializer_rejects_unsupported_version() -> None:
    data = bytearray(dumps(compile_source("")))
    data[4] = 2
    with pytest.raises(SerializationError):
        loads(fixed_checksum(bytes(data)))


def test_serializer_rejects_trailing_payload() -> None:
    data = dumps(compile_source(""))
    malformed = fixed_checksum(data[:-4] + b"\x00" + data[-4:])
    with pytest.raises(SerializationError):
        loads(malformed)


def test_disassembly_exact() -> None:
    assert disassemble(compile_source("print 1;")) == (
        "0000 CONST 0  ; 1\n0001 PRINT\n0002 HALT\n"
    )


def test_disassembly_escapes_string() -> None:
    text = disassemble(compile_source(r'print "a\n\t\"\\";'))
    assert r'"a\n\t\"\\"' in text


def test_step_limit_infinite_loop() -> None:
    with pytest.raises(StepLimitError):
        execute(compile_source("while (true) {}"), step_limit=10)


def test_step_limit_validation() -> None:
    for value in (0, -1, True, 1.5):
        with pytest.raises(ValueError):
            execute(compile_source(""), step_limit=value)


def test_step_limit_exceeds_not_equals() -> None:
    assert execute(compile_source(""), step_limit=1) == []


def test_public_exports_exact() -> None:
    assert len(microvm.__all__) == 19
    assert set(microvm.__all__) == {
        "tokenize", "Token", "parse", "compile_source", "Program", "Instr",
        "fold_constants", "execute", "dumps", "loads", "disassemble", "OPCODES",
        "OPCODE_NUMBERS", "MicroVMError", "LexError", "ParseError", "CompileError",
        "SerializationError", "VMRuntimeError",
    }


def test_opcode_numbers() -> None:
    assert len(microvm.OPCODES) == 21
    assert list(microvm.OPCODE_NUMBERS.values()) == list(range(1, 22))


def test_cli_run_success(tmp_path) -> None:
    source = tmp_path / "a.mv"
    source.write_text("print 5;", encoding="utf-8")
    result = subprocess.run(
        [sys.executable, "-m", "microvm", "run", str(source)],
        capture_output=True, text=True, check=False,
    )
    assert (result.returncode, result.stdout) == (0, "5\n")


def test_cli_usage_error(tmp_path) -> None:
    result = subprocess.run(
        [sys.executable, "-m", "microvm", "run"],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 2 and result.stdout == ""


def test_cli_unreadable_file(tmp_path) -> None:
    result = subprocess.run(
        [sys.executable, "-m", "microvm", "run", str(tmp_path / "missing")],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 2 and result.stdout == ""


def test_cli_microvm_error_buffers_output(tmp_path) -> None:
    source = tmp_path / "bad.mv"
    source.write_text("print 1; print 1 / 0;", encoding="utf-8")
    result = subprocess.run(
        [sys.executable, "-m", "microvm", "run", str(source)],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 3 and result.stdout == ""


def test_cli_build_exec_disasm(tmp_path) -> None:
    source = tmp_path / "a.mv"
    binary = tmp_path / "a.mvm"
    source.write_text("print 8 / 2;", encoding="utf-8")
    built = subprocess.run(
        [sys.executable, "-m", "microvm", "build", str(source), str(binary)],
        capture_output=True, text=True, check=False,
    )
    executed = subprocess.run(
        [sys.executable, "-m", "microvm", "exec", str(binary)],
        capture_output=True, text=True, check=False,
    )
    shown = subprocess.run(
        [sys.executable, "-m", "microvm", "disasm", str(binary)],
        capture_output=True, text=True, check=False,
    )
    assert built.returncode == 0 and executed.stdout == "4.0\n"
    assert shown.returncode == 0 and shown.stdout.endswith("HALT\n")
