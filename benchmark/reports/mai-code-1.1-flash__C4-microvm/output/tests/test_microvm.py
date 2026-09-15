import subprocess
import sys
import zlib

import pytest

import microvm
from microvm import (
    CompileError,
    LexError,
    ParseError,
    Program,
    SerializationError,
    StepLimitError,
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


def _run(src: str) -> list[str]:
    return execute(compile_source(src))


def test_tokenize_int_literal() -> None:
    tokens = tokenize("123")
    assert tokens[0].kind == "INT" and tokens[0].value == 123


def test_tokenize_float_literal() -> None:
    tokens = tokenize("1.5")
    assert tokens[0].kind == "FLOAT" and tokens[0].value == 1.5


def test_tokenize_float_exponent() -> None:
    tokens = tokenize("2.0E-2")
    assert tokens[0].kind == "FLOAT" and tokens[0].value == 0.02


def test_tokenize_rejects_dot_five() -> None:
    with pytest.raises(LexError):
        tokenize(".5")


def test_tokenize_rejects_trailing_dot() -> None:
    with pytest.raises(LexError):
        tokenize("1.")


def test_tokenize_decodes_string_escapes() -> None:
    tokens = tokenize('"a\\n\\t\\\\\\\""')
    assert tokens[0].value == 'a\n\t\\"'


def test_tokenize_skips_comments() -> None:
    tokens = tokenize("1 // hi\n2")
    assert [token.value for token in tokens] == [1, 2]


def test_tokenize_keywords() -> None:
    tokens = tokenize("let while true false and or not")
    assert len(tokens) == 7
    assert [token.kind for token in tokens] == ["KEYWORD"] * 7


def test_tokenize_longest_operator_match() -> None:
    tokens = tokenize("== != <= >= =")
    assert [token.text for token in tokens] == ["==", "!=", "<=", ">=", "="]


def test_tokenize_unexpected_character() -> None:
    with pytest.raises(LexError):
        tokenize("$")


def test_parse_let_statement() -> None:
    tree = parse("let x = 1 + 2;")
    assert len(tree) == 1


def test_parse_if_else_if() -> None:
    tree = parse("if (true) { print 1; } else if (false) { print 2; } else { print 3; }")
    assert len(tree) == 1


def test_parse_chained_comparison_error() -> None:
    with pytest.raises(ParseError):
        parse("1 < 2 < 3;")


def test_parse_missing_semicolon_error() -> None:
    with pytest.raises(ParseError):
        parse("print 1")


def test_compile_duplicate_let_error() -> None:
    with pytest.raises(CompileError):
        compile_source("let x = 1; let x = 2;")


def test_compile_undeclared_assign_error() -> None:
    with pytest.raises(CompileError):
        compile_source("x = 1;")


def test_compile_undeclared_read_error() -> None:
    with pytest.raises(CompileError):
        compile_source("print x;")


def test_compile_names_include_let_in_branches() -> None:
    program = compile_source("if (false) { let x = 3; } else { let y = 4; }")
    assert program.names == ["x", "y"]


def test_compile_print_literal_three_instructions() -> None:
    program = compile_source("print 1;")
    assert len(program.instructions) == 3


def test_execute_prints_ints_and_float() -> None:
    assert _run("print 5; print 8 / 2;") == ["5", "4.0"]


def test_execute_prints_bools() -> None:
    assert _run("print true; print false;") == ["true", "false"]


def test_execute_string_concatenation() -> None:
    assert _run("print \"a\" + \"b\";") == ["ab"]


def test_execute_numeric_addition() -> None:
    assert _run("print 1 + 2.5;") == ["3.5"]


def test_execute_div_zero_error() -> None:
    with pytest.raises(VMRuntimeError):
        _run("print 1 / 0;")


def test_execute_mod_zero_error() -> None:
    with pytest.raises(VMRuntimeError):
        _run("print 7 % 0;")


def test_execute_mod_sign_rule() -> None:
    assert _run("print -7 % 3;") == ["2"]


def test_execute_bool_not_int() -> None:
    assert _run("print true == 1;") == ["false"]


def test_execute_string_compare() -> None:
    assert _run("print \"b\" > \"a\";") == ["true"]


def test_execute_bool_compare_error() -> None:
    with pytest.raises(VMRuntimeError):
        _run("print true < 2;")


def test_execute_short_circuit_and() -> None:
    assert _run("print false and (1 / 0 == 0);") == ["false"]


def test_execute_short_circuit_or() -> None:
    assert _run("print true or (1 / 0 == 0);") == ["true"]


def test_execute_true_and_non_bool_runtime_error() -> None:
    with pytest.raises(VMRuntimeError):
        _run("print true and 5;")


def test_execute_unassigned_runtime_error() -> None:
    with pytest.raises(VMRuntimeError):
        _run("if (false) { let x = 1; } print x;")


def test_execute_if_condition_runtime_error() -> None:
    with pytest.raises(VMRuntimeError):
        _run("if (1) { print 1; }")


def test_execute_while_condition_runtime_error() -> None:
    with pytest.raises(VMRuntimeError):
        _run("while (1) { print 1; }")


def test_execute_step_limit_error() -> None:
    with pytest.raises(StepLimitError):
        execute(compile_source("while (true) {}"), step_limit=1)


def test_execute_invalid_step_limit_rejected() -> None:
    with pytest.raises(ValueError):
        execute(compile_source("print 1;"), step_limit=0)


def test_execute_invalid_bool_step_limit_rejected() -> None:
    with pytest.raises(ValueError):
        execute(compile_source("print 1;"), step_limit=True)


def test_fold_constants_addition() -> None:
    program = compile_source("print 1 + 2 * 3;", optimize=True)
    assert len(program.instructions) == 3


def test_fold_constants_div_zero_stays_unfolded() -> None:
    program = compile_source("print 1 / 0;", optimize=True)
    assert program.instructions[0].op == "CONST"


def test_fold_constants_false_and_x() -> None:
    folded = fold_constants(parse("let y = false and x;"))[0].value
    assert folded.value is False


def test_fold_constants_true_or_x() -> None:
    folded = fold_constants(parse("let y = true or x;"))[0].value
    assert folded.value is True


def test_fold_constants_true_and_nonbool_not_folded() -> None:
    folded = fold_constants(parse("let y = true and 5;"))[0].value
    assert folded.op == "and"


def test_serializer_round_trip() -> None:
    program = compile_source("let x = 5; print x;")
    assert execute(loads(dumps(program))) == ["5"]


def test_serializer_rejects_bad_magic() -> None:
    with pytest.raises(SerializationError):
        loads(b"BAD!\x01\x00\x00\x00\x00\x00\x00\x00")


def test_serializer_rejects_bad_version() -> None:
    data = bytearray(dumps(compile_source("print 1;")))
    data[4] = 9
    with pytest.raises(SerializationError):
        loads(data)


def test_serializer_rejects_checksum_mismatch() -> None:
    data = bytearray(dumps(compile_source("print 1;")))
    data[-1] ^= 0xFF
    with pytest.raises(SerializationError):
        loads(data)


def test_serializer_rejects_unknown_opcode() -> None:
    data = bytearray(dumps(compile_source("print 1;")))
    data[22] = 0xFF
    payload = data[4:-4]
    data[-4:] = (zlib.crc32(payload) & 0xFFFFFFFF).to_bytes(4, "big")
    with pytest.raises(SerializationError):
        loads(data)


def test_disassemble_exact_example() -> None:
    text = disassemble(compile_source("print 1;"))
    assert text == "0000 CONST 0  ; 1\n0001 PRINT\n0002 HALT\n"


def test_cli_run_success(tmp_path) -> None:
    path = tmp_path / "run.mv"
    path.write_text("let x = 5; print x; print 8 / 2;", encoding="utf-8")
    completed = subprocess.run([sys.executable, "-m", "microvm", "run", str(path)], capture_output=True, text=True)
    assert completed.returncode == 0 and completed.stdout == "5\n4.0\n"


def test_cli_build_and_exec_round_trip(tmp_path) -> None:
    src = tmp_path / "prog.mv"
    out = tmp_path / "prog.bin"
    src.write_text("let x = 5; print x;", encoding="utf-8")
    build = subprocess.run([sys.executable, "-m", "microvm", "build", str(src), str(out)], capture_output=True, text=True)
    assert build.returncode == 0
    exec_run = subprocess.run([sys.executable, "-m", "microvm", "exec", str(out)], capture_output=True, text=True)
    assert exec_run.returncode == 0 and exec_run.stdout == "5\n"


def test_cli_disasm_success(tmp_path) -> None:
    src = tmp_path / "prog.mv"
    out = tmp_path / "prog.bin"
    src.write_text("print 1;", encoding="utf-8")
    subprocess.run([sys.executable, "-m", "microvm", "build", str(src), str(out)], check=True)
    completed = subprocess.run([sys.executable, "-m", "microvm", "disasm", str(out)], capture_output=True, text=True)
    assert completed.stdout == "0000 CONST 0  ; 1\n0001 PRINT\n0002 HALT\n"


def test_cli_usage_exit_code() -> None:
    completed = subprocess.run([sys.executable, "-m", "microvm", "run"], capture_output=True, text=True)
    assert completed.returncode == 2


def test_cli_runtime_error_exit_code(tmp_path) -> None:
    path = tmp_path / "bad.mv"
    path.write_text("print 1 / 0;", encoding="utf-8")
    completed = subprocess.run([sys.executable, "-m", "microvm", "run", str(path)], capture_output=True, text=True)
    assert completed.returncode == 3 and completed.stdout == ""


def test_module_all_length() -> None:
    assert len(microvm.__all__) == 19


def test_program_is_program_instance() -> None:
    program = compile_source("print 1;")
    assert isinstance(program, Program)


def test_parse_does_not_require_eof_token() -> None:
    tree = parse("print 1 + 1;")
    assert len(tree) == 1
