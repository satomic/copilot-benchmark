import struct
import zlib

import pytest

from microvm import (
    CompileError, LexError, ParseError, SerializationError, VMRuntimeError,
    compile_source, disassemble, dumps, execute, loads, parse, tokenize,
)
from microvm.__main__ import main
from microvm.errors import StepLimitError


def run(source, optimize=False):
    return execute(compile_source(source, optimize=optimize))


def test_tokenize_keywords_and_case():
    tokens = tokenize("let IF true and or not false")
    assert [token.kind for token in tokens] == [
        "KEYWORD", "IDENT", "KEYWORD", "KEYWORD", "KEYWORD", "KEYWORD", "KEYWORD"]


def test_tokenize_numbers():
    tokens = tokenize("12 1.25 2.0E-2")
    assert [token.value for token in tokens] == [12, 1.25, 0.02]


def test_tokenize_string_escapes():
    token = tokenize(r'"a\n\t\"\\z"')[0]
    assert token.text == 'a\n\t"\\z'
    assert token.value == token.text


def test_tokenize_longest_operators():
    assert [item.text for item in tokenize("= == != < <= > >=")] == [
        "=", "==", "!=", "<", "<=", ">", ">="]


def test_tokenize_comment():
    assert [item.text for item in tokenize("print 1; // ignore\nprint 2;")] == [
        "print", "1", ";", "print", "2", ";"]


def test_token_offsets():
    assert tokenize("  foo")[0].offset == 2


def test_unexpected_character_offset():
    with pytest.raises(LexError) as caught:
        tokenize("@")
    assert caught.value.offset == 0


def test_float_missing_fraction_is_lex_error():
    with pytest.raises(LexError):
        tokenize("1.")


def test_leading_dot_is_lex_error():
    with pytest.raises(LexError):
        tokenize(".5")


def test_bad_exponent_is_lex_error():
    with pytest.raises(LexError):
        tokenize("1.2e+")


def test_bad_escape_is_lex_error():
    with pytest.raises(LexError):
        tokenize(r'"bad\q"')


def test_unterminated_string_is_lex_error():
    with pytest.raises(LexError):
        tokenize('"unfinished')


def test_newline_in_string_is_lex_error():
    with pytest.raises(LexError):
        tokenize('"line\nbreak"')


def test_parse_nested_control_statements():
    assert parse("if (true) { while (false) {} } else if (false) {}").statements


def test_parse_empty_program():
    assert parse("").statements == []


def test_parse_missing_semicolon_has_offset():
    with pytest.raises(ParseError) as caught:
        parse("print 1")
    assert caught.value.offset == len("print 1")


def test_parse_comparison_is_not_associative():
    with pytest.raises(ParseError):
        parse("print 1 < 2 < 3;")


def test_parse_requires_parenthesized_condition():
    with pytest.raises(ParseError):
        parse("if true {}")


def test_parse_rejects_assignment_expression():
    with pytest.raises(ParseError):
        parse("let x = 1; print x = 2;")


def test_literal_print_instruction_shape():
    program = compile_source("print 1;")
    assert [(i.op, i.arg) for i in program.instructions] == [
        ("CONST", 0), ("PRINT", None), ("HALT", None)]


def test_constant_pool_deduplicates_by_type():
    program = compile_source("print 1; print 1.0; print true; print 1;")
    assert program.constants == [1, 1.0, True]
    assert [program.instructions[i].arg for i in (0, 2, 4, 6)] == [0, 1, 2, 0]


def test_float_constant_pool_preserves_signed_zero():
    program = compile_source("print 0.0; print -0.0;", optimize=True)
    assert execute(program) == ["0.0", "-0.0"]


def test_duplicate_declaration_is_compile_error():
    with pytest.raises(CompileError):
        compile_source("let x = 1; { let x = 2; }")


def test_assignment_undeclared_is_compile_error():
    with pytest.raises(CompileError):
        compile_source("x = 1;")


def test_read_undeclared_is_compile_error():
    with pytest.raises(CompileError):
        compile_source("print x;")


def test_declaration_in_branch_is_global():
    assert compile_source("if (false) { let x = 1; }").names == ["x"]


def test_uninitialized_branch_declaration_fails_at_runtime():
    with pytest.raises(VMRuntimeError, match="x"):
        run("if (false) { let x = 1; } print x;")


def test_arithmetic_integer_and_float():
    assert run("print 2 + 3; print 4 / 2;") == ["5", "2.0"]


def test_string_concatenation():
    assert run('print "a" + "b";') == ["ab"]


def test_bad_string_addition_is_runtime_error():
    with pytest.raises(VMRuntimeError):
        run('print "a" + 1;')


def test_float_arithmetic_result_type():
    assert run("print 1 + 2.0; print 5 - 2.0; print 3 * 2.0;") == [
        "3.0", "3.0", "6.0"]


def test_negative_modulo_matches_python_sign_rule():
    assert run("print -7 % 3;") == ["2"]


def test_modulo_requires_integers():
    with pytest.raises(VMRuntimeError):
        run("print 4.0 % 2;")


def test_division_by_zero_is_runtime_error():
    with pytest.raises(VMRuntimeError):
        run("print 1 / 0;")


def test_modulo_by_zero_is_runtime_error():
    with pytest.raises(VMRuntimeError):
        run("print 1 % 0;")


def test_unary_negation():
    assert run("print -3; print -1.5;") == ["-3", "-1.5"]


def test_negation_rejects_bool():
    with pytest.raises(VMRuntimeError):
        run("print -true;")


def test_boolean_equality_does_not_equal_integer():
    assert run("print true == 1; print true != 1;") == ["false", "true"]


def test_integer_and_float_equality_is_numeric():
    assert run("print 1 == 1.0;") == ["true"]


def test_equality_between_different_types_is_false():
    assert run('print 1 == "1";') == ["false"]


def test_string_ordering():
    assert run('print "a" < "b";') == ["true"]


def test_bool_ordering_is_runtime_error():
    with pytest.raises(VMRuntimeError):
        run("print true < false;")


def test_not_requires_bool():
    with pytest.raises(VMRuntimeError):
        run("print not 1;")


def test_and_short_circuits_false_left():
    assert run("print false and (1 / 0 == 0);") == ["false"]


def test_or_short_circuits_true_left():
    assert run("print true or (1 / 0 == 0);") == ["true"]


def test_and_validates_evaluated_right_operand():
    with pytest.raises(VMRuntimeError):
        run("print true and 5;")


def test_or_validates_evaluated_right_operand():
    with pytest.raises(VMRuntimeError):
        run("print false or 5;")


def test_condition_requires_bool():
    with pytest.raises(VMRuntimeError):
        run("if (1) {}")


def test_while_condition_requires_bool():
    with pytest.raises(VMRuntimeError):
        run("while (0) {}")


def test_if_else_if_execution():
    assert run('let x = 3; if (x > 5) { print "big"; } else if (x > 2) { print "mid"; } else { print "small"; }') == ["mid"]


def test_blocks_share_scope():
    assert run("{ let x = 3; } print x;") == ["3"]


def test_assignment_updates_value():
    assert run("let x = 2; x = x * 3; print x;") == ["6"]


def test_while_loop_executes():
    assert run("let x = 3; while (x > 0) { print x; x = x - 1; }") == [
        "3", "2", "1"]


def test_boolean_print_format():
    assert run("print true; print false;") == ["true", "false"]


def test_string_print_is_raw():
    assert run('print "a\\nb";') == ["a\nb"]


def test_optimizer_folds_nested_arithmetic():
    optimized = compile_source("print 1 + 2 * 3;", optimize=True)
    assert [(item.op, item.arg) for item in optimized.instructions] == [
        ("CONST", 0), ("PRINT", None), ("HALT", None)]
    assert execute(optimized) == ["7"]


def test_unoptimized_arithmetic_has_more_instructions():
    assert len(compile_source("print 1 + 2 * 3;").instructions) > 3


def test_optimizer_does_not_fold_division_by_zero():
    with pytest.raises(VMRuntimeError):
        execute(compile_source("print 1 / 0;", optimize=True))


def test_optimizer_preserves_strict_bool_check():
    with pytest.raises(VMRuntimeError):
        execute(compile_source("let y = true and 5; print y;", optimize=True))


def test_optimizer_can_fold_nonexecuted_and_operand():
    assert execute(compile_source("print false and (1 / 0 == 0);",
                                  optimize=True)) == ["false"]


def test_short_circuit_logic_uses_jumps():
    ops = [item.op for item in compile_source("print true and false;").instructions]
    assert "JUMP_IF_FALSE" in ops and "JUMP" in ops


def test_exact_disassembly():
    assert disassemble(compile_source("print 1;")) == (
        "0000 CONST 0  ; 1\n0001 PRINT\n0002 HALT\n")


def test_disassembly_escapes_string_constant():
    assert '"a\\n\\"b"' in disassemble(compile_source('print "a\\n\\"b";'))


def test_step_limit_rejects_infinite_loop():
    with pytest.raises(StepLimitError):
        execute(compile_source("while (true) {}"), step_limit=15)


def test_step_limit_must_be_positive_int():
    for value in (0, -1, True, 1.0):
        with pytest.raises(ValueError):
            execute(compile_source(""), step_limit=value)


def test_step_limit_allows_exact_number_of_instructions():
    assert execute(compile_source(""), step_limit=1) == []


def test_serializer_round_trip():
    original = compile_source('let x = 1.5; print "hello"; print x;')
    restored = loads(dumps(original))
    assert restored == original
    assert execute(restored) == execute(original)


def test_serializer_is_deterministic():
    program = compile_source("print true;")
    assert dumps(program) == dumps(program)


def test_serializer_rejects_int_outside_i64():
    from microvm import Program

    with pytest.raises(SerializationError):
        dumps(Program([1 << 63], [], []))


def test_serializer_rejects_bad_magic():
    data = bytearray(dumps(compile_source("")))
    data[0] ^= 1
    with pytest.raises(SerializationError):
        loads(bytes(data))


def test_serializer_rejects_checksum_corruption():
    data = bytearray(dumps(compile_source("")))
    data[5] ^= 1
    with pytest.raises(SerializationError, match="checksum"):
        loads(bytes(data))


def test_serializer_rejects_truncation():
    with pytest.raises(SerializationError):
        loads(dumps(compile_source(""))[:-2])


def test_serializer_rejects_trailing_bytes_after_valid_checksum():
    data = dumps(compile_source(""))
    body = data[4:-4] + b"x"
    malformed = data[:4] + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)
    with pytest.raises(SerializationError, match="trailing"):
        loads(malformed)


def test_cli_run_success(tmp_path, capsys):
    source = tmp_path / "program.mv"
    source.write_text("let x = 5; print x; print 8 / 2;", encoding="utf-8")
    assert main(["run", str(source)]) == 0
    assert capsys.readouterr().out == "5\n4.0\n"


def test_cli_build_exec_and_disasm(tmp_path, capsys):
    source, binary = tmp_path / "input.mv", tmp_path / "output.mvm"
    source.write_text("print 7;", encoding="utf-8")
    assert main(["build", str(source), str(binary)]) == 0
    assert main(["exec", str(binary)]) == 0
    assert capsys.readouterr().out == "7\n"
    assert main(["disasm", str(binary)]) == 0
    assert capsys.readouterr().out.endswith("HALT\n")


def test_cli_bad_command_returns_usage_code(capsys):
    assert main(["unknown"]) == 2
    assert capsys.readouterr().out == ""


def test_cli_missing_file_returns_usage_code(tmp_path, capsys):
    assert main(["run", str(tmp_path / "absent.mv")]) == 2
    assert capsys.readouterr().out == ""


def test_cli_invalid_step_limit_returns_usage_code(tmp_path, capsys):
    source = tmp_path / "empty.mv"
    source.write_text("", encoding="utf-8")
    assert main(["run", str(source), "--step-limit", "0"]) == 2
    assert capsys.readouterr().out == ""


def test_cli_vm_failure_buffers_output(tmp_path, capsys):
    source = tmp_path / "bad.mv"
    source.write_text("print 1; print 1 / 0;", encoding="utf-8")
    assert main(["run", str(source)]) == 3
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "zero" in captured.err


def test_package_exports_exactly_nineteen_names():
    import microvm

    assert len(microvm.__all__) == 19
