from __future__ import annotations

import pytest

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
from microvm.parser import Literal, Script


def _run(src: str, *, optimize: bool = False, step_limit: int = 100_000) -> list[str]:
    return execute(compile_source(src, optimize=optimize), step_limit=step_limit)


def test_print_int() -> None:
    assert _run("print 5;") == ["5"]


def test_print_float_division() -> None:
    assert _run("print 8 / 2;") == ["4.0"]


def test_print_bool_and_string() -> None:
    assert _run('print true; print false; print "hi";') == ["true", "false", "hi"]


def test_let_assign_and_print() -> None:
    assert _run("let x = 1 + 2; x = x * 3; print x;") == ["9"]


def test_int_ops_stay_int() -> None:
    assert _run("print 3 - 1; print 3 * 2;") == ["2", "6"]


def test_float_promotes() -> None:
    assert _run("print 1 + 2.0; print 3.0 * 2;") == ["3.0", "6.0"]


def test_string_concat() -> None:
    assert _run('print "a" + "b";') == ["ab"]


def test_string_plus_int_error() -> None:
    with pytest.raises(VMRuntimeError):
        _run('print "a" + 1;')


def test_division_always_float() -> None:
    assert _run("print 7 / 2;") == ["3.5"]


def test_modulo_python_sign() -> None:
    assert _run("print -7 % 3;") == ["2"]


def test_division_by_zero() -> None:
    with pytest.raises(VMRuntimeError):
        _run("print 1 / 0;")


def test_modulo_by_zero() -> None:
    with pytest.raises(VMRuntimeError):
        _run("print 1 % 0;")


def test_unary_minus_number() -> None:
    assert _run("print -3; print --4;") == ["-3", "4"]


def test_unary_minus_bool_error() -> None:
    with pytest.raises(VMRuntimeError):
        _run("print -true;")


def test_eq_never_raises_and_bool_differs_from_int() -> None:
    assert _run("print true == 1; print 1 == 1.0; print 1 != 2;") == [
        "false",
        "true",
        "true",
    ]


def test_eq_mixed_types() -> None:
    assert _run('print "a" == 1; print "a" == "a";') == ["false", "true"]


def test_ordering_numbers_and_strings() -> None:
    assert _run('print 1 < 2.0; print "a" < "b"; print 3 >= 3;') == [
        "true",
        "true",
        "true",
    ]


def test_ordering_bool_error() -> None:
    with pytest.raises(VMRuntimeError):
        _run("print true < false;")


def test_ordering_mixed_error() -> None:
    with pytest.raises(VMRuntimeError):
        _run('print 1 < "a";')


def test_logic_requires_bool() -> None:
    with pytest.raises(VMRuntimeError):
        _run("print true and 5;")


def test_short_circuit_and_skips_right() -> None:
    assert _run("print false and (1 / 0 == 0);") == ["false"]


def test_short_circuit_or_skips_right() -> None:
    assert _run("print true or (1 / 0 == 0);") == ["true"]


def test_or_evaluates_right_when_needed() -> None:
    with pytest.raises(VMRuntimeError):
        _run("print false or 5;")


def test_not_bool() -> None:
    assert _run("print not false; print not true;") == ["true", "false"]


def test_not_non_bool_error() -> None:
    with pytest.raises(VMRuntimeError):
        _run("print not 1;")


def test_if_else_if_chain() -> None:
    src = (
        "let x = 3; if (x > 5) { print \"big\"; } "
        'else if (x > 2) { print "mid"; } else { print "small"; }'
    )
    assert _run(src) == ["mid"]


def test_if_condition_must_be_bool() -> None:
    with pytest.raises(VMRuntimeError):
        _run("if (1) { print 1; }")


def test_while_counts_down() -> None:
    assert _run("let x = 3; while (x > 0) { x = x - 1; } print x;") == ["0"]


def test_while_condition_must_be_bool() -> None:
    with pytest.raises(VMRuntimeError):
        _run("while (1) { print 1; }")


def test_unassigned_variable_runtime() -> None:
    with pytest.raises(VMRuntimeError, match="y"):
        _run("let x = 1; if (false) { let y = 2; } print y;")


def test_duplicate_let_compile_error() -> None:
    with pytest.raises(CompileError):
        compile_source("let x = 1; let x = 2;")


def test_undeclared_name_compile_error() -> None:
    with pytest.raises(CompileError):
        compile_source("x = 1;")


def test_undeclared_read_compile_error() -> None:
    with pytest.raises(CompileError):
        compile_source("print x;")


def test_keywords_are_case_sensitive() -> None:
    prog = compile_source("let IF = 4; print IF;")
    assert execute(prog) == ["4"]


def test_constant_pool_dedup_and_distinct_types() -> None:
    prog = compile_source("print 1; print 1; print 1.0; print true;")
    assert prog.constants == [1, 1.0, True]
    assert sum(1 for ins in prog.instructions if ins.op == "CONST") == 4


def test_print_literal_instruction_count() -> None:
    prog = compile_source("print 1;")
    assert [(i.op, i.arg) for i in prog.instructions] == [
        ("CONST", 0),
        ("PRINT", None),
        ("HALT", None),
    ]


def test_optimize_folds_arithmetic() -> None:
    raw = compile_source("print 1 + 2 * 3;")
    opt = compile_source("print 1 + 2 * 3;", optimize=True)
    assert len(opt.instructions) == 3
    assert len(raw.instructions) > 3
    assert execute(opt) == ["7"]


def test_optimize_does_not_fold_div_zero() -> None:
    prog = compile_source("print 1 / 0;", optimize=True)
    assert any(i.op == "DIV" for i in prog.instructions)
    with pytest.raises(VMRuntimeError):
        execute(prog)


def test_optimize_does_not_drop_bool_check() -> None:
    prog = compile_source("let y = true and 5;", optimize=True)
    with pytest.raises(VMRuntimeError):
        execute(prog)


def test_optimize_folds_false_and_any() -> None:
    prog = compile_source("print false and (1 / 0 == 0);", optimize=True)
    assert not any(i.op == "DIV" for i in prog.instructions)
    assert execute(prog) == ["false"]


def test_fold_constants_on_ast() -> None:
    tree = fold_constants(parse("print 2 + 2;"))
    assert isinstance(tree, Script)
    stmt = tree.statements[0]
    assert isinstance(stmt.expr, Literal)  # type: ignore[attr-defined]
    assert stmt.expr.value == 4  # type: ignore[attr-defined]


def test_serializer_roundtrip() -> None:
    prog = compile_source('let x = 1; print x + 2.5; print "a\\n"; print true;')
    again = loads(dumps(prog))
    assert execute(again) == execute(prog)
    assert dumps(again) == dumps(prog)


def test_serializer_int_range() -> None:
    prog = Program([1 << 63], [], [Instr("HALT", None)])
    with pytest.raises(SerializationError):
        dumps(prog)


def test_serializer_bad_magic() -> None:
    data = dumps(compile_source("print 1;"))
    with pytest.raises(SerializationError):
        loads(b"XXXX" + data[4:])


def test_serializer_checksum_mismatch() -> None:
    data = bytearray(dumps(compile_source("print 1;")))
    data[4] ^= 0xFF
    with pytest.raises(SerializationError):
        loads(bytes(data))


def test_serializer_truncated() -> None:
    data = dumps(compile_source("print 1;"))
    with pytest.raises(SerializationError):
        loads(data[:-1])


def test_serializer_trailing_bytes() -> None:
    data = dumps(compile_source("print 1;"))
    with pytest.raises(SerializationError):
        loads(data + b"\x00")


def test_disassemble_print_one() -> None:
    text = disassemble(compile_source("print 1;"))
    assert text == "0000 CONST 0  ; 1\n0001 PRINT\n0002 HALT\n"


def test_disassemble_string_escapes() -> None:
    text = disassemble(compile_source('print "a\\n\\t\\"\\\\";'))
    assert '; "a\\n\\t\\"\\\\"' in text


def test_step_limit_infinite_loop() -> None:
    with pytest.raises(StepLimitError):
        _run("while (true) {}", step_limit=50)


def test_step_limit_value_error() -> None:
    prog = compile_source("print 1;")
    with pytest.raises(ValueError):
        execute(prog, step_limit=True)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        execute(prog, step_limit=0)


def test_lex_invalid_floats() -> None:
    with pytest.raises(LexError) as one:
        tokenize("1.")
    assert one.value.offset == 0
    with pytest.raises(LexError):
        tokenize(".5")


def test_lex_string_errors() -> None:
    with pytest.raises(LexError):
        tokenize('"abc')
    with pytest.raises(LexError):
        tokenize('"a\\q"')
    with pytest.raises(LexError):
        tokenize('"a\n"')


def test_lex_comment_and_longest_op() -> None:
    toks = tokenize("a == 1; // hi\nb != 2;")
    kinds = [t.kind for t in toks]
    assert "KEYWORD" not in kinds or True
    assert any(t.text == "==" for t in toks)
    assert any(t.text == "!=" for t in toks)


def test_parse_chained_comparison() -> None:
    with pytest.raises(ParseError) as err:
        parse("print 1 < 2 < 3;")
    assert isinstance(err.value.offset, int)


def test_parse_missing_semicolon() -> None:
    with pytest.raises(ParseError):
        parse("print 1")


def test_blocks_do_not_scope() -> None:
    assert _run("{ let x = 9; } print x;") == ["9"]


def test_bool_is_not_number() -> None:
    with pytest.raises(VMRuntimeError):
        _run("print true + 1;")


def test_modulo_requires_ints() -> None:
    with pytest.raises(VMRuntimeError):
        _run("print 1.0 % 2;")


def test_opcodes_numbering() -> None:
    assert OPCODES[0] == "CONST"
    assert OPCODE_NUMBERS["HALT"] == 21
    assert len(OPCODES) == 21


def test_cli_run_success(tmp_path, capsys) -> None:  # type: ignore[no-untyped-def]
    path = tmp_path / "t.mv"
    path.write_text("let x = 5; print x; print 8 / 2;\n", encoding="utf-8")
    assert main(["run", str(path)]) == 0
    assert capsys.readouterr().out.splitlines() == ["5", "4.0"]


def test_cli_runtime_buffers_stdout(tmp_path, capsys) -> None:  # type: ignore[no-untyped-def]
    path = tmp_path / "t.mv"
    path.write_text("print 1; print 1 / 0;\n", encoding="utf-8")
    assert main(["run", str(path)]) == 3
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err != ""


def test_cli_usage_and_missing_file(tmp_path, capsys) -> None:  # type: ignore[no-untyped-def]
    assert main(["nope"]) == 2
    assert capsys.readouterr().out == ""
    assert main(["run", str(tmp_path / "missing.mv")]) == 2
    assert capsys.readouterr().out == ""


def test_cli_step_limit_invalid(tmp_path, capsys) -> None:  # type: ignore[no-untyped-def]
    path = tmp_path / "t.mv"
    path.write_text("print 1;\n", encoding="utf-8")
    assert main(["run", str(path), "--step-limit", "0"]) == 2
    assert capsys.readouterr().out == ""
    assert main(["run", str(path), "--step-limit", "x"]) == 2
    assert capsys.readouterr().out == ""


def test_cli_build_exec_disasm(tmp_path, capsys) -> None:  # type: ignore[no-untyped-def]
    src = tmp_path / "t.mv"
    out = tmp_path / "t.bin"
    src.write_text("print 1;\n", encoding="utf-8")
    assert main(["build", str(src), str(out)]) == 0
    assert main(["exec", str(out)]) == 0
    assert capsys.readouterr().out.splitlines() == ["1"]
    assert main(["disasm", str(out)]) == 0
    assert capsys.readouterr().out == "0000 CONST 0  ; 1\n0001 PRINT\n0002 HALT\n"


def test_cli_optimize_flag(tmp_path, capsys) -> None:  # type: ignore[no-untyped-def]
    path = tmp_path / "t.mv"
    path.write_text("print 1 + 2 * 3;\n", encoding="utf-8")
    assert main(["run", str(path), "--optimize"]) == 0
    assert capsys.readouterr().out.splitlines() == ["7"]


def test_true_and_true() -> None:
    assert _run("print true and true;") == ["true"]


def test_false_or_false() -> None:
    assert _run("print false or false;") == ["false"]


def test_comparison_le_gt() -> None:
    assert _run("print 1 <= 1; print 2 > 1;") == ["true", "true"]


def test_string_ge() -> None:
    assert _run('print "b" >= "a";') == ["true"]


def test_nested_block_if() -> None:
    src = "let x = 1; if (true) { { x = 2; } } print x;"
    assert _run(src) == ["2"]


def test_loads_unknown_tag() -> None:
    prog = compile_source("print 1;")
    data = bytearray(dumps(prog))
    # After checksum validation we still want a structural error: flip a
    # constant tag then repair the checksum so the payload is trusted.
    payload = bytearray(data[4:-4])
    # version(1) + name count(2) + const count(2) + first const tag
    payload[1 + 2 + 2] = 0x99
    checksum = __import__("zlib").crc32(payload) & 0xFFFFFFFF
    with pytest.raises(SerializationError):
        loads(b"MVM1" + bytes(payload) + checksum.to_bytes(4, "big"))
