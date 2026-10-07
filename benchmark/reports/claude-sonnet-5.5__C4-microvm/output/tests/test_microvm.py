import subprocess
import sys

import pytest

import microvm
from microvm import (
    CompileError, Instr, LexError, MicroVMError, ParseError, Program,
    SerializationError, VMRuntimeError, compile_source, disassemble, dumps,
    execute, fold_constants, loads, parse, tokenize,
)
from microvm.__main__ import main
from microvm.errors import StepLimitError


def run(src, **kw):
    return execute(compile_source(src, optimize=kw.pop("optimize", False)), **kw)


def both(src):
    return run(src), run(src, optimize=True)


# ---- lexer ----
def test_tokenize_basic_kinds():
    toks = tokenize("let x = 1 + 2.5;")
    assert [t.kind for t in toks] == ["KEYWORD", "IDENT", "OP", "INT", "OP", "FLOAT", "OP"]
    assert toks[3].value == 1 and toks[5].value == 2.5 and toks[1].offset == 4


def test_tokenize_no_eof_token():
    assert tokenize("") == []
    assert tokenize("  // only a comment") == []


def test_float_exponent():
    assert [t.value for t in tokenize("1.5e3 2.0E-2")] == [1500.0, 0.02]


@pytest.mark.parametrize("src", ["1.", ".5", "1.e3", "1.5e", "@", "#"])
def test_lex_errors(src):
    with pytest.raises(LexError):
        tokenize(src)


def test_lex_error_offset():
    with pytest.raises(LexError) as info:
        tokenize("let x = $;")
    assert info.value.offset == 8


def test_string_escapes():
    tok = tokenize(r'"a\n\t\"\\b"')[0]
    assert tok.value == 'a\n\t"\\b' and tok.text == tok.value


@pytest.mark.parametrize("src", [r'"\q"', '"abc', '"a\nb"'])
def test_bad_strings(src):
    with pytest.raises(LexError):
        tokenize(src)


def test_keywords_case_sensitive():
    toks = tokenize("IF if Print")
    assert [t.kind for t in toks] == ["IDENT", "KEYWORD", "IDENT"]


def test_longest_match_operators():
    assert [t.text for t in tokenize("== = != <= < >= >")] == ["==", "=", "!=", "<=", "<", ">=", ">"]


# ---- parser ----
def test_comparison_not_associative():
    with pytest.raises(ParseError):
        parse("print 1 < 2 < 3;")


@pytest.mark.parametrize("src", [
    "let x = 1", "print ;", "if (true) print 1;", "x = ;", "{", "}", "let = 1;",
    "while true {}", "print (1;", "else { }",
])
def test_parse_errors_have_offset(src):
    with pytest.raises(ParseError) as info:
        parse(src)
    assert isinstance(info.value.offset, int) and 0 <= info.value.offset <= len(src)


def test_lex_error_passes_through_parse():
    with pytest.raises(LexError):
        parse("print 1.;")


def test_else_if_chain():
    src = 'let x = 3; if (x > 5) { print "big"; } else if (x > 2) { print "mid"; } else { print "small"; }'
    assert run(src) == ["mid"]


# ---- semantics ----
def test_arithmetic_types():
    assert run("print 1 + 2; print 1 + 2.0; print 2 * 3.5; print 5 - 7;") == ["3", "3.0", "7.0", "-2"]


def test_division_is_float():
    assert run("print 7 / 2; print 4 / 2;") == ["3.5", "2.0"]


def test_modulo_sign_rule():
    assert run("print -7 % 3; print 7 % -3;") == ["2", "-2"]


def test_modulo_requires_ints():
    with pytest.raises(VMRuntimeError):
        run("print 7.0 % 2;")


@pytest.mark.parametrize("src", ["print 1 / 0;", "print 1 % 0;", "print 1.0 / 0.0;"])
def test_division_by_zero(src):
    with pytest.raises(VMRuntimeError):
        run(src)


def test_string_concat_and_errors():
    assert run('print "a" + "b";') == ["ab"]
    for src in ['print "a" + 1;', 'print "a" - "b";', "print true + true;"]:
        with pytest.raises(VMRuntimeError):
            run(src)


def test_unary_minus():
    assert run("print -5; print -(2.5); print - -3;") == ["-5", "-2.5", "3"]
    for src in ['print -"a";', "print -true;"]:
        with pytest.raises(VMRuntimeError):
            run(src)


def test_equality_rules():
    assert run('print 1 == 1.0; print true == 1; print "a" == "a"; print 1 != "1"; print true != 1;') == [
        "true", "false", "true", "true", "true"]


def test_ordering_rules():
    assert run('print 1 < 2.5; print "a" < "b"; print 2 >= 2.0; print "b" <= "a";') == [
        "true", "true", "true", "false"]
    for src in ["print true < false;", 'print 1 < "a";', "print 1 > true;"]:
        with pytest.raises(VMRuntimeError):
            run(src)


def test_logic_requires_bool():
    assert run("print not false; print true and false; print false or true;") == ["true", "false", "true"]
    for src in ["print true and 5;", "print 5 and true;", "print false or 1;", "print not 1;", "print 0 or true;"]:
        with pytest.raises(VMRuntimeError):
            run(src)


def test_short_circuit():
    assert run("print false and (1 / 0 == 0);") == ["false"]
    assert run("print true or (1 / 0 == 0);") == ["true"]
    with pytest.raises(VMRuntimeError):
        run("print true and (1 / 0 == 0);")


def test_short_circuit_uses_jumps():
    ops = [i.op for i in compile_source("print true and false;").instructions]
    assert "JUMP_IF_FALSE" in ops


def test_conditions_must_be_bool():
    for src in ["if (1) { print 1; }", "while (0) { }", 'if ("x") { }']:
        with pytest.raises(VMRuntimeError):
            run(src)


def test_print_rendering():
    assert run('print 1; print 2.0; print true; print false; print "hi";') == ["1", "2.0", "true", "false", "hi"]


def test_while_loop():
    assert run("let i = 0; let s = 0; while (i < 5) { s = s + i; i = i + 1; } print s;") == ["10"]


def test_no_block_scope():
    assert run("{ let x = 4; } print x;") == ["4"]


def test_redeclare_is_compile_error():
    with pytest.raises(CompileError):
        compile_source("let x = 1; let x = 2;")
    with pytest.raises(CompileError):
        compile_source("let x = 1; { let x = 2; }")


def test_undeclared_names_compile_error():
    with pytest.raises(CompileError):
        compile_source("x = 1;")
    with pytest.raises(CompileError):
        compile_source("print y;")


def test_never_assigned_variable_runtime_error():
    with pytest.raises(VMRuntimeError, match="y"):
        run("if (false) { let y = 1; } print y;")


# ---- compiler ----
def test_print_literal_three_instructions():
    prog = compile_source("print 1;")
    assert prog.instructions == [Instr("CONST", 0), Instr("PRINT", None), Instr("HALT", None)]


def test_constant_pool_dedup_by_type():
    prog = compile_source("print 1; print 1.0; print true; print 1; print 0.0; print -0.0 ; print false;")
    assert prog.constants[:3] == [1, 1.0, True]
    assert [type(c) for c in prog.constants[:3]] == [int, float, bool]
    assert sum(1 for c in prog.constants if c == 1 and type(c) is int) == 1


def test_single_halt_at_end():
    prog = compile_source("let x = 1; while (x < 3) { x = x + 1; } if (x == 3) { print x; }")
    ops = [i.op for i in prog.instructions]
    assert ops.count("HALT") == 1 and ops[-1] == "HALT"


def test_names_in_declaration_order():
    assert compile_source("let b = 1; let a = 2;").names == ["b", "a"]


def test_empty_program():
    assert compile_source("").instructions == [Instr("HALT", None)]
    assert run("") == []


def test_opcode_tables():
    assert len(microvm.OPCODES) == 21
    assert microvm.OPCODE_NUMBERS["CONST"] == 1 and microvm.OPCODE_NUMBERS["HALT"] == 21


def test_public_api():
    assert len(microvm.__all__) == 19
    for name in microvm.__all__:
        assert hasattr(microvm, name)


# ---- optimizer ----
def test_fold_reduces_instructions():
    assert len(compile_source("print 1 + 2 * 3;", optimize=True).instructions) == 3
    assert len(compile_source("print 1 + 2 * 3;").instructions) > 3
    assert run("print 1 + 2 * 3;", optimize=True) == ["7"]


def test_fold_keeps_division_by_zero():
    with pytest.raises(VMRuntimeError):
        run("print 1 / 0;", optimize=True)
    with pytest.raises(VMRuntimeError):
        run("print 1 % 0;", optimize=True)


def test_fold_keeps_type_errors():
    with pytest.raises(VMRuntimeError):
        run('print "a" + 1;', optimize=True)


def test_fold_true_and_x_not_dropped():
    with pytest.raises(VMRuntimeError):
        run("let y = true and 5;", optimize=True)
    with pytest.raises(VMRuntimeError):
        run("let y = false or 5;", optimize=True)


def test_fold_short_circuit_literals():
    assert len(compile_source("print false and (1 / 0 == 0);", optimize=True).instructions) == 3
    assert run("print true or 5;", optimize=True) == ["true"]


def test_fold_equivalence_over_programs():
    srcs = [
        "print 1 == 1.0; print true == 1; print -(3 - 5); print not true;",
        'print "a" + "b"; print "a" < "b"; print 7 / 2 + 1;',
        "let x = 2 * 3; print x % 4; print (1 < 2) and (2 < 3);",
    ]
    for src in srcs:
        a, b = both(src)
        assert a == b


def test_fold_constants_direct():
    tree = parse("print 1 + 2;")
    assert fold_constants(tree) == ("program", [("print", ("lit", 3))])


# ---- vm ----
def test_step_limit_terminates():
    with pytest.raises(StepLimitError):
        run("while (true) { }", step_limit=1000)
    assert issubclass(StepLimitError, VMRuntimeError)


def test_step_limit_boundary():
    prog = compile_source("print 1;")
    assert execute(prog, step_limit=3) == ["1"]
    with pytest.raises(StepLimitError):
        execute(prog, step_limit=2)


@pytest.mark.parametrize("bad", [0, -1, True, 1.5, "3", None])
def test_bad_step_limit(bad):
    with pytest.raises(ValueError):
        execute(compile_source("print 1;"), step_limit=bad)


# ---- serializer ----
SAMPLE = 'let a = 1; let b = 2.5; let c = "h\\u00e9llo"; let d = true; let e = -9223372036854775808; print a; print b; print c; print d;'


def test_round_trip():
    prog = compile_source('let a = 1; let b = 2.5; let c = "h\u00e9\\n"; let d = true; print c; print a + b; print d;')
    again = loads(dumps(prog))
    assert again == prog
    assert execute(again) == execute(prog)


def test_dumps_deterministic_and_layout():
    prog = compile_source("print 1;")
    data = dumps(prog)
    assert data == dumps(prog) and data[:4] == b"MVM1" and data[4] == 1


def test_int_range_check():
    with pytest.raises(SerializationError):
        dumps(Program([2 ** 63], [], [Instr("HALT", None)]))
    dumps(Program([2 ** 63 - 1, -(2 ** 63)], [], [Instr("HALT", None)]))


def test_corrupt_magic_and_version():
    data = dumps(compile_source("print 1;"))
    with pytest.raises(SerializationError):
        loads(b"XVM1" + data[4:])
    import struct
    import zlib
    body = bytes([2]) + data[5:-4]
    with pytest.raises(SerializationError):
        loads(b"MVM1" + body + struct.pack(">I", zlib.crc32(body)))


def test_corrupt_checksum_and_bitflip():
    data = bytearray(dumps(compile_source("print 1;")))
    data[10] ^= 0xFF
    with pytest.raises(SerializationError):
        loads(bytes(data))


def test_truncation_and_trailing():
    data = dumps(compile_source('let a = 1; print a + 2;'))
    for cut in range(len(data)):
        with pytest.raises(SerializationError):
            loads(data[:cut])
    with pytest.raises(SerializationError):
        loads(data + b"\x00")


def _reseal(body):
    import struct
    import zlib
    return b"MVM1" + body + struct.pack(">I", zlib.crc32(body))


def test_bad_tag_opcode_bool_with_valid_checksum():
    import struct
    ins = struct.pack(">BI", 21, 0xFFFFFFFF)
    head = b"\x01" + struct.pack(">H", 0)
    bad_tag = head + struct.pack(">H", 1) + b"\x09\x00" + struct.pack(">I", 1) + ins
    bad_bool = head + struct.pack(">H", 1) + b"\x04\x02" + struct.pack(">I", 1) + ins
    bad_op = head + struct.pack(">H", 0) + struct.pack(">I", 1) + struct.pack(">BI", 22, 0xFFFFFFFF)
    for body in (bad_tag, bad_bool, bad_op):
        with pytest.raises(SerializationError):
            loads(_reseal(body))


def test_arg_rules_on_load():
    import struct
    head = b"\x01" + struct.pack(">H", 0) + struct.pack(">H", 0) + struct.pack(">I", 1)
    with pytest.raises(SerializationError):
        loads(_reseal(head + struct.pack(">BI", 1, 0xFFFFFFFF)))  # CONST without arg
    with pytest.raises(SerializationError):
        loads(_reseal(head + struct.pack(">BI", 21, 5)))  # HALT with arg


def test_dumps_rejects_bad_instrs():
    with pytest.raises(SerializationError):
        dumps(Program([], [], [Instr("CONST", None)]))
    with pytest.raises(SerializationError):
        dumps(Program([], [], [Instr("HALT", 3)]))


def test_loads_rejects_non_bytes():
    with pytest.raises(SerializationError):
        loads("MVM1")


# ---- disassembler ----
def test_disassemble_exact():
    assert disassemble(compile_source("print 1;")) == "0000 CONST 0  ; 1\n0001 PRINT\n0002 HALT\n"


def test_disassemble_constant_rendering():
    text = disassemble(compile_source('print "a\\n\\t\\"\\\\"; print true; print 2.5;'))
    assert '  ; "a\\n\\t\\"\\\\"' in text
    assert "; true" in text and "; 2.5" in text


# ---- CLI ----
def test_cli_run(tmp_path, capsys):
    src = tmp_path / "t.mv"
    src.write_text("let x = 5; print x; print 8 / 2;")
    assert main(["run", str(src)]) == 0
    assert capsys.readouterr().out == "5\n4.0\n"


def test_cli_build_exec_disasm(tmp_path, capsys):
    src = tmp_path / "t.mv"
    out = tmp_path / "t.bin"
    src.write_text("print 1 + 2;")
    assert main(["build", str(src), str(out), "--optimize"]) == 0
    assert main(["exec", str(out)]) == 0
    assert capsys.readouterr().out == "3\n"
    assert main(["disasm", str(out)]) == 0
    assert capsys.readouterr().out == "0000 CONST 0  ; 3\n0001 PRINT\n0002 HALT\n"


def test_cli_runtime_error_has_empty_stdout(tmp_path, capsys):
    src = tmp_path / "t.mv"
    src.write_text("print 1; print 1 / 0;")
    assert main(["run", str(src)]) == 3
    captured = capsys.readouterr()
    assert captured.out == "" and captured.err


def test_cli_step_limit(tmp_path, capsys):
    src = tmp_path / "t.mv"
    src.write_text("while (true) { }")
    assert main(["run", str(src), "--step-limit", "50"]) == 3
    assert main(["run", str(src), "--step-limit", "0"]) == 2
    assert main(["run", str(src), "--step-limit", "abc"]) == 2
    assert capsys.readouterr().out == ""


def test_cli_usage_errors(tmp_path):
    assert main([]) == 2
    assert main(["bogus"]) == 2
    assert main(["run"]) == 2
    assert main(["run", str(tmp_path / "missing.mv")]) == 2
    assert main(["exec", str(tmp_path / "missing.bin")]) == 2


def test_cli_bad_binary_and_syntax(tmp_path):
    bad = tmp_path / "bad.bin"
    bad.write_bytes(b"garbage")
    assert main(["exec", str(bad)]) == 3
    assert main(["disasm", str(bad)]) == 3
    src = tmp_path / "s.mv"
    src.write_text("let = ;")
    assert main(["run", str(src)]) == 3
    assert main(["build", str(src), str(tmp_path / "o.bin")]) == 3


def test_cli_module_entry(tmp_path):
    src = tmp_path / "t.mv"
    src.write_text("let x = 5; print x; print 8 / 2;")
    proc = subprocess.run([sys.executable, "-m", "microvm", "run", str(src)],
                          capture_output=True, text=True)
    assert proc.returncode == 0 and proc.stdout.split() == ["5", "4.0"]


def test_errors_hierarchy():
    assert issubclass(LexError, MicroVMError) and issubclass(SerializationError, MicroVMError)
    assert issubclass(VMRuntimeError, MicroVMError)
