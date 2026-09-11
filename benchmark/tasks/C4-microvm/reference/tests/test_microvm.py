"""Reference test suite for microvm."""

from __future__ import annotations

import subprocess
import sys

import pytest

import microvm as mv


def run(src: str, **kw) -> list[str]:
    return mv.execute(mv.compile_source(src, **kw))


# -- lexer -------------------------------------------------------------------

def test_tokenize_kinds():
    kinds = [t.kind for t in mv.tokenize('let x = 1;')]
    assert kinds == ["KEYWORD", "IDENT", "OP", "INT", "OP"]


def test_keywords_are_case_sensitive():
    assert mv.tokenize("IF")[0].kind == "IDENT"
    assert mv.tokenize("if")[0].kind == "KEYWORD"


def test_float_token():
    tok = mv.tokenize("1.5e3")[0]
    assert tok.kind == "FLOAT" and tok.value == 1500.0


def test_bare_dot_float_is_lex_error():
    with pytest.raises(mv.LexError):
        mv.tokenize("let x = 1.;")
    with pytest.raises(mv.LexError):
        mv.tokenize("let x = .5;")


def test_string_escapes():
    tok = mv.tokenize(r'"a\n\t\"\\"')[0]
    assert tok.value == 'a\n\t"\\'


def test_unknown_escape_is_lex_error():
    with pytest.raises(mv.LexError):
        mv.tokenize(r'"\q"')


def test_unterminated_string():
    with pytest.raises(mv.LexError) as info:
        mv.tokenize('"abc')
    assert info.value.offset == 0


def test_comment_skipped():
    assert [t.text for t in mv.tokenize("1 // hi\n2")] == ["1", "2"]


def test_lex_error_offset():
    with pytest.raises(mv.LexError) as info:
        mv.tokenize("let @")
    assert info.value.offset == 4


def test_no_eof_token():
    assert len(mv.tokenize("1")) == 1


# -- parser ------------------------------------------------------------------

@pytest.mark.parametrize("src", [
    "print 1", "let = 1;", "let x 1;", "if true { }", "while (true) print 1;",
    "print 1 < 2 < 3;", "x + 1;", "{ print 1;", "print (1;",
])
def test_parse_errors(src):
    with pytest.raises(mv.ParseError):
        mv.parse(src)


def test_parse_error_offset_is_int():
    with pytest.raises(mv.ParseError) as info:
        mv.parse("print ;")
    assert isinstance(info.value.offset, int)


# -- compile errors ----------------------------------------------------------

def test_duplicate_let():
    with pytest.raises(mv.CompileError):
        mv.compile_source("let a = 1; let a = 2;")


def test_assign_undeclared():
    with pytest.raises(mv.CompileError):
        mv.compile_source("a = 1;")


def test_read_undeclared():
    with pytest.raises(mv.CompileError):
        mv.compile_source("print a;")


# -- program shape -----------------------------------------------------------

def test_constant_dedup():
    program = mv.compile_source("print 1 + 1;")
    assert program.constants == [1]


def test_bool_int_float_are_distinct_constants():
    program = mv.compile_source("print 1; print 1.0; print true;")
    assert program.constants == [1, 1.0, True]


def test_single_trailing_halt():
    program = mv.compile_source("print 1; print 2;")
    ops = [i.op for i in program.instructions]
    assert ops[-1] == "HALT" and ops.count("HALT") == 1


def test_names_in_declaration_order():
    program = mv.compile_source("let b = 1; let a = 2;")
    assert program.names == ["b", "a"]


def test_opcode_numbers():
    assert mv.OPCODE_NUMBERS["CONST"] == 1
    assert mv.OPCODE_NUMBERS["HALT"] == 21
    assert len(mv.OPCODES) == 21


# -- semantics ---------------------------------------------------------------

def test_int_arithmetic():
    assert run("print 2 + 3 * 4 - 1;") == ["13"]


def test_division_always_float():
    assert run("print 8 / 2;") == ["4.0"]


def test_modulo_python_sign():
    assert run("print -7 % 3;") == ["2"]


def test_string_concat():
    assert run('print "a" + "b";') == ["ab"]


def test_string_plus_int_raises():
    with pytest.raises(mv.VMRuntimeError):
        run('print "a" + 1;')


def test_bool_arithmetic_raises():
    with pytest.raises(mv.VMRuntimeError):
        run("print true + 1;")


@pytest.mark.parametrize("src", ["print 1 / 0;", "print 1 % 0;", "print 1.5 / 0.0;"])
def test_division_by_zero(src):
    with pytest.raises(mv.VMRuntimeError):
        run(src)


def test_modulo_requires_ints():
    with pytest.raises(mv.VMRuntimeError):
        run("print 1.5 % 2;")


def test_bool_not_equal_to_int():
    assert run("print true == 1;") == ["false"]


def test_int_float_cross_equality():
    assert run("print 1 == 1.0;") == ["true"]


def test_different_types_not_equal():
    assert run('print 1 == "1";') == ["false"]
    assert run('print 1 != "1";') == ["true"]


def test_string_ordering():
    assert run('print "a" < "b";') == ["true"]


def test_bool_ordering_raises():
    with pytest.raises(mv.VMRuntimeError):
        run("print true < false;")


def test_mixed_ordering_raises():
    with pytest.raises(mv.VMRuntimeError):
        run('print 1 < "a";')


def test_negate_bool_raises():
    with pytest.raises(mv.VMRuntimeError):
        run("print -true;")


def test_not_requires_bool():
    with pytest.raises(mv.VMRuntimeError):
        run("print not 1;")


def test_condition_must_be_bool():
    with pytest.raises(mv.VMRuntimeError):
        run("if (1) { print 1; }")


def test_print_formats():
    assert run('print 1; print 2.5; print 4 / 2; print true; print "s";') == [
        "1", "2.5", "2.0", "true", "s"]


# -- short circuit -----------------------------------------------------------

def test_and_short_circuits():
    assert run("print false and (1 / 0 == 0);") == ["false"]


def test_or_short_circuits():
    assert run("print true or (1 / 0 == 0);") == ["true"]


def test_evaluated_operand_must_be_bool():
    with pytest.raises(mv.VMRuntimeError):
        run("print true and 5;")


def test_or_right_evaluated_when_needed():
    assert run("print false or true;") == ["true"]


# -- variables and control flow ----------------------------------------------

def test_unassigned_variable():
    with pytest.raises(mv.VMRuntimeError) as info:
        run("if (false) { let z = 1; } print z;")
    assert "z" in str(info.value)


def test_while_countdown():
    assert run("let i = 3; while (i > 0) { print i; i = i - 1; }") == ["3", "2", "1"]


def test_else_if_chain():
    src = 'let x = 3; if (x > 5) { print "a"; } else if (x > 2) { print "b"; } else { print "c"; }'
    assert run(src) == ["b"]


def test_blocks_do_not_scope():
    assert run("{ let x = 1; } print x;") == ["1"]


def test_step_limit_raises():
    with pytest.raises(mv.MicroVMError) as info:
        run("while (true) {}")
    from microvm.errors import StepLimitError
    assert isinstance(info.value, StepLimitError)
    assert isinstance(info.value, mv.VMRuntimeError)


def test_step_limit_small():
    from microvm.errors import StepLimitError
    with pytest.raises(StepLimitError):
        mv.execute(mv.compile_source("print 1;"), step_limit=1)


@pytest.mark.parametrize("bad", [0, -1, True, 1.5, "10"])
def test_step_limit_validation(bad):
    with pytest.raises(ValueError):
        mv.execute(mv.compile_source("print 1;"), step_limit=bad)


# -- optimizer ---------------------------------------------------------------

def test_folding_canonical_example():
    program = mv.compile_source("print 1 + 2 * 3;", optimize=True)
    assert [i.op for i in program.instructions] == ["CONST", "PRINT", "HALT"]


def test_unoptimized_is_bigger():
    assert len(mv.compile_source("print 1 + 2 * 3;").instructions) > 3


def test_division_by_zero_not_folded():
    with pytest.raises(mv.VMRuntimeError):
        run("print 1 / 0;", optimize=True)


def test_true_and_x_not_folded():
    with pytest.raises(mv.VMRuntimeError):
        run("let y = true and 5; print y;", optimize=True)


def test_false_and_x_folds_safely():
    assert run("print false and (1 / 0 == 0);", optimize=True) == ["false"]


@pytest.mark.parametrize("src", [
    "let i = 0; while (i < 3) { print i * 2; i = i + 1; }",
    'if (1 + 1 == 2) { print "yes"; } else { print "no"; }',
    "print not (1 > 2); print -(2 + 3);",
])
def test_optimizer_preserves_behaviour(src):
    assert run(src, optimize=True) == run(src)


# -- serializer --------------------------------------------------------------

def test_round_trip():
    program = mv.compile_source('let x = 2; while (x > 0) { print "hi"; x = x - 1; }')
    again = mv.loads(mv.dumps(program))
    assert mv.execute(again) == mv.execute(program)


def test_dumps_deterministic():
    program = mv.compile_source("print 1;")
    assert mv.dumps(program) == mv.dumps(program)


def test_magic_and_version():
    data = mv.dumps(mv.compile_source("print 1;"))
    assert data[:4] == b"MVM1" and data[4] == 1


def test_bad_magic():
    with pytest.raises(mv.SerializationError):
        mv.loads(b"XXXX" + mv.dumps(mv.compile_source("print 1;"))[4:])


def test_crc_corruption():
    data = bytearray(mv.dumps(mv.compile_source("print 1;")))
    data[10] ^= 0xFF
    with pytest.raises(mv.SerializationError):
        mv.loads(bytes(data))


def test_truncation():
    data = mv.dumps(mv.compile_source("print 1;"))
    with pytest.raises(mv.SerializationError):
        mv.loads(data[:10])


def test_int_out_of_i64_range():
    program = mv.compile_source("print 1;")
    program.constants[0] = 2 ** 63
    with pytest.raises(mv.SerializationError):
        mv.dumps(program)


# -- disassembler ------------------------------------------------------------

def test_disassemble_exact():
    text = mv.disassemble(mv.compile_source("print 1;"))
    assert text == "0000 CONST 0  ; 1\n0001 PRINT\n0002 HALT\n"


def test_disassemble_string_escaped():
    text = mv.disassemble(mv.compile_source('print "a\\nb";'))
    assert '; "a\\nb"' in text


def test_disassemble_bool_lowercase():
    assert "; true" in mv.disassemble(mv.compile_source("print true;"))


# -- package surface -----------------------------------------------------------

def test_all_is_exact():
    assert len(mv.__all__) == 19


def test_error_hierarchy():
    from microvm.errors import StepLimitError
    assert issubclass(StepLimitError, mv.VMRuntimeError)
    for name in ("LexError", "ParseError", "CompileError", "SerializationError", "VMRuntimeError"):
        assert issubclass(getattr(mv, name), mv.MicroVMError)


# -- CLI -----------------------------------------------------------------------

def _cli(*args):
    return subprocess.run([sys.executable, "-m", "microvm", *args],
                          capture_output=True, text=True)


def test_cli_run(tmp_path):
    src = tmp_path / "t.mv"
    src.write_text("let x = 5; print x; print 8 / 2;", encoding="utf-8")
    done = _cli("run", str(src))
    assert done.returncode == 0
    assert done.stdout == "5\n4.0\n"


def test_cli_build_exec_disasm(tmp_path):
    src = tmp_path / "t.mv"
    src.write_text("print 1;", encoding="utf-8")
    out = tmp_path / "t.mvb"
    assert _cli("build", str(src), str(out), "--optimize").returncode == 0
    done = _cli("exec", str(out))
    assert done.returncode == 0 and done.stdout == "1\n"
    disasm = _cli("disasm", str(out))
    assert disasm.returncode == 0 and disasm.stdout.startswith("0000 CONST 0")


def test_cli_usage_errors(tmp_path):
    assert _cli().returncode == 2
    assert _cli("frobnicate").returncode == 2
    assert _cli("run", str(tmp_path / "missing.mv")).returncode == 2
    src = tmp_path / "t.mv"
    src.write_text("print 1;", encoding="utf-8")
    assert _cli("run", str(src), "--step-limit", "0").returncode == 2


def test_cli_error_exit_three(tmp_path):
    src = tmp_path / "t.mv"
    src.write_text("print 1 / 0;", encoding="utf-8")
    done = _cli("run", str(src))
    assert done.returncode == 3
    assert done.stdout == ""
    assert done.stderr != ""


def test_cli_stdout_empty_on_midway_error(tmp_path):
    src = tmp_path / "t.mv"
    src.write_text('print "before"; print 1 / 0;', encoding="utf-8")
    done = _cli("run", str(src))
    assert done.returncode == 3 and done.stdout == ""


def test_cli_step_limit_flag(tmp_path):
    src = tmp_path / "t.mv"
    src.write_text("while (true) {}", encoding="utf-8")
    done = _cli("run", str(src), "--step-limit", "50")
    assert done.returncode == 3
