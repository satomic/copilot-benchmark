"""Hidden verification suite for task C4. Not visible to the model under test.

Every name, field and format asserted here is pinned by task.md (sections 2, 4,
7, 8, 9, 10). Nothing reaches into unspecified internals: the AST is never
inspected, and only spec-mandated module-level entry points are called.
"""
import importlib
import struct
import subprocess
import sys
import zlib
from pathlib import Path

import pytest

_IGNORED_DIRS = {"__pycache__", "_verify", ".pytest_cache", ".git", ".ruff_cache", ".mypy_cache"}


@pytest.fixture(scope="module")
def mv():
    sys.path.insert(0, ".")
    return importlib.import_module("microvm")


@pytest.fixture
def run(mv):
    def go(src, optimize=False, step_limit=100_000):
        return mv.execute(mv.compile_source(src, optimize=optimize), step_limit=step_limit)
    return go


def cli(*args, timeout=60):
    return subprocess.run(
        [sys.executable, "-m", "microvm", *args],
        capture_output=True, text=True, timeout=timeout, cwd=".",
    )


# --------------------------------------------------------------------------- #
# 1. lexer
# --------------------------------------------------------------------------- #

def test_token_kinds_sequence(mv):
    assert [t.kind for t in mv.tokenize("let x = 1;")] == [
        "KEYWORD", "IDENT", "OP", "INT", "OP"]


@pytest.mark.parametrize("word", "let print if else while true false and or not".split())
def test_keywords(mv, word):
    tok = mv.tokenize(word)[0]
    assert tok.kind == "KEYWORD" and tok.text == word and tok.value == word


@pytest.mark.parametrize("word", ["IF", "Let", "PRINT", "True", "While", "AND"])
def test_uppercase_keywords_are_identifiers(mv, word):
    assert mv.tokenize(word)[0].kind == "IDENT"


@pytest.mark.parametrize("src,value", [("0", 0), ("42", 42), ("007", 7)])
def test_int_tokens(mv, src, value):
    tok = mv.tokenize(src)[0]
    assert tok.kind == "INT" and tok.value == value and isinstance(tok.value, int)


@pytest.mark.parametrize("src,value", [("1.5", 1.5), ("0.25", 0.25), ("1.5e3", 1500.0),
                                       ("2.0E-2", 0.02), ("10.0", 10.0)])
def test_float_tokens(mv, src, value):
    tok = mv.tokenize(src)[0]
    assert tok.kind == "FLOAT" and tok.value == value and isinstance(tok.value, float)


@pytest.mark.parametrize("src", ["1.", ".5", "let x = 1.;", "print .5;"])
def test_bare_dot_floats_are_lex_errors(mv, src):
    with pytest.raises(mv.LexError):
        mv.tokenize(src)


def test_string_token_decoded(mv):
    tok = mv.tokenize('"hi"')[0]
    assert tok.kind == "STRING" and tok.text == "hi" and tok.value == "hi"


def test_string_escapes(mv):
    assert mv.tokenize(r'"a\n\t\"\\z"')[0].value == 'a\n\t"\\z'


@pytest.mark.parametrize("src", [r'"\q"', r'"\0"', '"abc', '"a\nb"', r'"end\\'])
def test_string_lex_errors(mv, src):
    with pytest.raises(mv.LexError):
        mv.tokenize(src)


def test_comment_to_end_of_line(mv):
    assert [t.text for t in mv.tokenize("1 // x = 2;\n3")] == ["1", "3"]


@pytest.mark.parametrize("op", ["+", "-", "*", "/", "%", "(", ")", "{", "}", ";",
                                "=", "==", "!=", "<", "<=", ">", ">="])
def test_operator_tokens(mv, op):
    tok = mv.tokenize(op)[0]
    assert tok.kind == "OP" and tok.text == op


def test_longest_match(mv):
    assert [t.text for t in mv.tokenize("a==b")] == ["a", "==", "b"]
    assert [t.text for t in mv.tokenize("a=b")] == ["a", "=", "b"]
    assert [t.text for t in mv.tokenize("a<=b")] == ["a", "<=", "b"]


def test_offsets_zero_based(mv):
    tokens = mv.tokenize("let x = 1;")
    assert [t.offset for t in tokens] == [0, 4, 6, 8, 9]


def test_no_eof_token(mv):
    assert len(mv.tokenize("1")) == 1
    assert mv.tokenize("") == []


@pytest.mark.parametrize("src,offset", [("@", 0), ("let $", 4), ("x = 1; #", 7)])
def test_lex_error_offset(mv, src, offset):
    with pytest.raises(mv.LexError) as info:
        mv.tokenize(src)
    assert info.value.offset == offset


def test_token_is_frozen_dataclass(mv):
    tok = mv.tokenize("1")[0]
    with pytest.raises(Exception):
        tok.kind = "OP"


# --------------------------------------------------------------------------- #
# 2. parser errors
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("src", [
    "print 1", "let x = 1", "x = 1", "let = 1;", "let x 1;", "let x = ;",
    "if true { }", "if (true) print 1;", "while (true) print 1;", "while true { }",
    "else { }", "{ print 1;", "print (1;", "print 1);", "print ;",
    "print 1 < 2 < 3;", "print 1 == 2 == 3;", "print 1 <= 2 > 3;",
    "let 1 = x;", "print 1 + ;", "print 1 + * 2;",
])
def test_parse_errors(mv, src):
    with pytest.raises((mv.ParseError, mv.LexError)):
        mv.parse(src)


def test_parse_error_offset_attribute(mv):
    with pytest.raises(mv.ParseError) as info:
        mv.parse("print 1 < 2 < 3;")
    assert isinstance(info.value.offset, int) and info.value.offset >= 0


def test_lex_error_passes_through_parse(mv):
    with pytest.raises(mv.LexError):
        mv.parse("print @;")


def test_else_if_chain_parses(mv):
    mv.parse("if (true) { } else if (false) { } else { }")


def test_empty_program_parses(mv):
    mv.parse("")
    mv.parse("// only a comment")


# --------------------------------------------------------------------------- #
# 3. compile errors
# --------------------------------------------------------------------------- #

def test_duplicate_let(mv):
    with pytest.raises(mv.CompileError):
        mv.compile_source("let a = 1; let a = 2;")


def test_duplicate_let_inside_block(mv):
    with pytest.raises(mv.CompileError):
        mv.compile_source("let a = 1; { let a = 2; }")


def test_assign_undeclared(mv):
    with pytest.raises(mv.CompileError):
        mv.compile_source("a = 1;")


def test_read_undeclared(mv):
    with pytest.raises(mv.CompileError):
        mv.compile_source("print a;")


def test_read_before_let_in_source_fails_somewhere(mv):
    """Use before a later `let` must fail, but the spec supports two readings.

    Section 1 says a `let` "declares the name for the whole program", which a
    hoisting compiler may honour by accepting this at compile time and raising
    the never-assigned VMRuntimeError when the read executes. A sequential
    compiler raises CompileError instead. Both are consistent with the text,
    so both are accepted; silently printing something is the only wrong answer.
    """
    program = "print a; let a = 1;"
    with pytest.raises((mv.CompileError, mv.VMRuntimeError)):
        mv.execute(mv.compile_source(program))


# --------------------------------------------------------------------------- #
# 4. program shape and opcodes
# --------------------------------------------------------------------------- #

def test_opcodes_tuple_exact(mv):
    assert tuple(mv.OPCODES) == (
        "CONST", "LOAD", "STORE", "ADD", "SUB", "MUL", "DIV", "MOD", "NEG", "NOT",
        "EQ", "NE", "LT", "LE", "GT", "GE", "JUMP", "JUMP_IF_FALSE", "PRINT", "POP", "HALT")


def test_opcode_numbers_exact(mv):
    assert mv.OPCODE_NUMBERS == {name: i + 1 for i, name in enumerate(mv.OPCODES)}


def test_constant_pool_dedup(mv):
    assert mv.compile_source("print 1 + 1 + 1;").constants == [1]


def test_bool_int_float_distinct_constants(mv):
    constants = mv.compile_source("print 1; print 1.0; print true;").constants
    assert len(constants) == 3
    kinds = [(type(c), c) for c in constants]
    assert (int, 1) in kinds and (float, 1.0) in kinds and (bool, True) in kinds


def test_string_constants_pooled(mv):
    assert mv.compile_source('print "a"; print "a";').constants == ["a"]


def test_single_trailing_halt(mv):
    ops = [i.op for i in mv.compile_source("let i = 0; while (i < 2) { i = i + 1; }").instructions]
    assert ops[-1] == "HALT" and ops.count("HALT") == 1


def test_print_literal_is_three_instructions(mv):
    program = mv.compile_source("print 1;")
    assert [i.op for i in program.instructions] == ["CONST", "PRINT", "HALT"]
    assert program.instructions[0].arg == 0


def test_instr_fields(mv):
    instr = mv.compile_source("print 1;").instructions[0]
    assert instr.op == "CONST" and instr.arg == 0
    assert mv.compile_source("print 1;").instructions[1].arg is None


def test_names_declaration_order(mv):
    program = mv.compile_source("let b = 1; { let z = 2; } let a = 3;")
    assert program.names == ["b", "z", "a"]


def test_all_ops_are_legal(mv):
    for src in ("print 1 + 2;", "let x = 1; x = 2; print x;",
                "if (true) { print 1; } else { print 2; }",
                "print true and false; print true or false;"):
        for instr in mv.compile_source(src).instructions:
            assert instr.op in mv.OPCODES
            has_arg = instr.op in ("CONST", "LOAD", "STORE", "JUMP", "JUMP_IF_FALSE")
            assert (instr.arg is not None) == has_arg


def test_jump_targets_in_range(mv):
    program = mv.compile_source(
        "let i = 0; while (i < 3) { if (i == 1) { print i; } i = i + 1; }")
    for instr in program.instructions:
        if instr.op in ("JUMP", "JUMP_IF_FALSE"):
            assert 0 <= instr.arg <= len(program.instructions)


# --------------------------------------------------------------------------- #
# 5. arithmetic and comparison semantics
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("src,expected", [
    ("print 2 + 3;", "5"), ("print 2 - 5;", "-3"), ("print 3 * 4;", "12"),
    ("print 2 + 3 * 4;", "14"), ("print (2 + 3) * 4;", "20"),
    ("print 10 - 2 - 3;", "5"), ("print 2 * 3 % 4;", "2"),
    ("print -3;", "-3"), ("print - -3;", "3"), ("print -2 * 3;", "-6"),
    ("print 1 + 2.5;", "3.5"), ("print 2.0 * 3;", "6.0"), ("print 1.5 - 0.5;", "1.0"),
])
def test_arithmetic(run, src, expected):
    assert run(src) == [expected]


@pytest.mark.parametrize("src,expected", [
    ("print 8 / 2;", "4.0"), ("print 7 / 2;", "3.5"), ("print 1 / 8;", "0.125"),
    ("print 3.0 / 2;", "1.5"),
])
def test_division_always_float(run, src, expected):
    assert run(src) == [expected]


@pytest.mark.parametrize("src,expected", [
    ("print 7 % 3;", "1"), ("print -7 % 3;", "2"), ("print 7 % -3;", "-2"),
])
def test_modulo_python_sign(run, src, expected):
    assert run(src) == [expected]


@pytest.mark.parametrize("src", ["print 1 / 0;", "print 1 % 0;", "print 1.0 / 0.0;",
                                 "print 5 / (2 - 2);"])
def test_zero_division_raises(mv, run, src):
    with pytest.raises(mv.VMRuntimeError):
        run(src)


@pytest.mark.parametrize("src", ["print 1.5 % 2;", "print 4 % 2.0;"])
def test_modulo_requires_int(mv, run, src):
    with pytest.raises(mv.VMRuntimeError):
        run(src)


def test_string_concat(run):
    assert run('print "foo" + "bar";') == ["foobar"]


@pytest.mark.parametrize("src", ['print "a" + 1;', 'print 1 + "a";', 'print "a" - "b";',
                                 "print true + 1;", "print true + true;", 'print "a" * 2;'])
def test_arithmetic_type_errors(mv, run, src):
    with pytest.raises(mv.VMRuntimeError):
        run(src)


def test_negate_requires_number(mv, run):
    with pytest.raises(mv.VMRuntimeError):
        run("print -true;")
    with pytest.raises(mv.VMRuntimeError):
        run('print -"a";')


@pytest.mark.parametrize("src,expected", [
    ("print 1 == 1;", "true"), ("print 1 == 2;", "false"),
    ("print 1 == 1.0;", "true"), ("print 1.5 == 1.5;", "true"),
    ("print true == true;", "true"), ("print true == false;", "false"),
    ('print "a" == "a";', "true"), ('print "a" == "b";', "false"),
    ("print true == 1;", "false"), ("print false == 0;", "false"),
    ('print 1 == "1";', "false"), ('print true == "true";', "false"),
    ("print 1 != 1.0;", "false"), ("print true != 1;", "true"),
])
def test_equality(run, src, expected):
    assert run(src) == [expected]


@pytest.mark.parametrize("src,expected", [
    ("print 1 < 2;", "true"), ("print 2 <= 2;", "true"), ("print 3 > 4;", "false"),
    ("print 2 >= 3;", "false"), ("print 1 < 1.5;", "true"), ("print 2.5 > 2;", "true"),
    ('print "a" < "b";', "true"), ('print "b" <= "a";', "false"),
    ('print "A" < "a";', "true"),
])
def test_ordering(run, src, expected):
    assert run(src) == [expected]


@pytest.mark.parametrize("src", ["print true < false;", "print 1 < true;",
                                 'print 1 < "a";', 'print "a" > 1;'])
def test_ordering_type_errors(mv, run, src):
    with pytest.raises(mv.VMRuntimeError):
        run(src)


@pytest.mark.parametrize("src,expected", [
    ("print not true;", "false"), ("print not false;", "true"),
    ("print not 1 == 2;", "true"),
    ("print true and true;", "true"), ("print true and false;", "false"),
    ("print false or true;", "true"), ("print false or false;", "false"),
    ("print not false and true;", "true"),
    ("print true or false and false;", "true"),
])
def test_logic(run, src, expected):
    assert run(src) == [expected]


@pytest.mark.parametrize("src", ["print not 1;", 'print not "a";'])
def test_not_requires_bool(mv, run, src):
    with pytest.raises(mv.VMRuntimeError):
        run(src)


# --------------------------------------------------------------------------- #
# 6. short circuit
# --------------------------------------------------------------------------- #

def test_and_short_circuits_past_error(run):
    assert run("print false and (1 / 0 == 0);") == ["false"]


def test_or_short_circuits_past_error(run):
    assert run("print true or (1 / 0 == 0);") == ["true"]


def test_and_right_evaluated_when_left_true(run):
    assert run("print true and (2 > 1);") == ["true"]


@pytest.mark.parametrize("src", ["print true and 5;", 'print false or "x";',
                                 "print 1 and true;", "print 0 or false;"])
def test_evaluated_logical_operand_must_be_bool(mv, run, src):
    with pytest.raises(mv.VMRuntimeError):
        run(src)


def test_nested_short_circuit(run):
    assert run("print false and (true or (1 / 0 == 0));") == ["false"]


def test_chain_short_circuit(run):
    assert run("print true or (1 / 0 == 0) or (2 / 0 == 0);") == ["true"]


# --------------------------------------------------------------------------- #
# 7. variables and control flow
# --------------------------------------------------------------------------- #

def test_let_and_print(run):
    assert run("let x = 5; print x;") == ["5"]


def test_assignment(run):
    assert run("let x = 1; x = x + 1; print x;") == ["2"]


def test_blocks_share_scope(run):
    assert run("{ let x = 1; } print x;") == ["1"]


def test_unassigned_variable_raises(mv, run):
    with pytest.raises(mv.VMRuntimeError) as info:
        run("if (false) { let ghost = 1; } print ghost;")
    assert "ghost" in str(info.value)


def test_assigned_in_taken_branch(run):
    assert run("if (true) { let z = 9; } print z;") == ["9"]


def test_if_true(run):
    assert run('if (2 > 1) { print "yes"; }') == ["yes"]


def test_if_false_no_else(run):
    assert run('if (1 > 2) { print "no"; }') == []


def test_if_else(run):
    assert run('if (1 > 2) { print "a"; } else { print "b"; }') == ["b"]


def test_else_if_chain(run):
    src = 'let x = 3; if (x > 5) { print "a"; } else if (x > 2) { print "b"; } else { print "c"; }'
    assert run(src) == ["b"]


def test_else_if_falls_to_final_else(run):
    src = 'let x = 1; if (x > 5) { print "a"; } else if (x > 2) { print "b"; } else { print "c"; }'
    assert run(src) == ["c"]


def test_while_countdown(run):
    assert run("let i = 3; while (i > 0) { print i; i = i - 1; }") == ["3", "2", "1"]


def test_while_never_entered(run):
    assert run('while (false) { print "x"; } print "end";') == ["end"]


def test_nested_while(run):
    src = ("let i = 0; while (i < 2) { let_j_reset = 0; j = 0; i = i + 1; }")
    # nested loops via two variables
    src = ("let i = 0; let j = 0; let total = 0;"
           "while (i < 3) { j = 0; while (j < 2) { total = total + 1; j = j + 1; } i = i + 1; }"
           "print total;")
    assert run(src) == ["6"]


def test_while_with_if_inside(run):
    src = ("let i = 0; while (i < 5) { if (i % 2 == 0) { print i; } i = i + 1; }")
    assert run(src) == ["0", "2", "4"]


@pytest.mark.parametrize("src", ["if (1) { }", "while (1 + 1) { }", 'if ("true") { }'])
def test_condition_must_be_bool(mv, run, src):
    with pytest.raises(mv.VMRuntimeError):
        run(src)


def test_print_formats(run):
    assert run('print 1; print 2.5; print 4 / 2; print true; print false; print "s t";') == [
        "1", "2.5", "2.0", "true", "false", "s t"]


def test_print_string_with_escapes(run):
    assert run(r'print "a\nb";') == ["a\nb"]


# --------------------------------------------------------------------------- #
# 8. step limit
# --------------------------------------------------------------------------- #

def test_infinite_loop_hits_step_limit(mv, run):
    with pytest.raises(mv.VMRuntimeError):
        run("while (true) {}", step_limit=1000)


def test_step_limit_error_subclass(mv):
    from microvm.errors import StepLimitError
    assert issubclass(StepLimitError, mv.VMRuntimeError)
    with pytest.raises(StepLimitError):
        mv.execute(mv.compile_source("while (true) {}"), step_limit=500)


def test_default_step_limit_terminates(mv):
    with pytest.raises(mv.VMRuntimeError):
        mv.execute(mv.compile_source("while (true) {}"))


def test_small_program_within_default(run):
    assert run("let i = 0; while (i < 100) { i = i + 1; } print i;") == ["100"]


def test_tight_step_limit_on_ok_program(mv):
    from microvm.errors import StepLimitError
    with pytest.raises(StepLimitError):
        mv.execute(mv.compile_source("print 1;"), step_limit=1)


@pytest.mark.parametrize("bad", [0, -5, True, False, 1.0, "100", None])
def test_step_limit_validation(mv, bad):
    with pytest.raises(ValueError):
        mv.execute(mv.compile_source("print 1;"), step_limit=bad)


# --------------------------------------------------------------------------- #
# 9. optimizer
# --------------------------------------------------------------------------- #

def test_canonical_fold(mv):
    program = mv.compile_source("print 1 + 2 * 3;", optimize=True)
    assert [i.op for i in program.instructions] == ["CONST", "PRINT", "HALT"]
    assert program.constants[program.instructions[0].arg] == 7


def test_unoptimized_has_more_instructions(mv):
    assert len(mv.compile_source("print 1 + 2 * 3;").instructions) > 3


def test_fold_preserves_int_type(mv):
    constants = mv.compile_source("print 2 + 3;", optimize=True).constants
    value = constants[0]
    assert value == 5 and isinstance(value, int) and not isinstance(value, bool)


def test_fold_division_yields_float(mv, run):
    program = mv.compile_source("print 8 / 2;", optimize=True)
    assert mv.execute(program) == ["4.0"]


def test_fold_comparison(mv):
    program = mv.compile_source("print 2 > 1;", optimize=True)
    assert [i.op for i in program.instructions] == ["CONST", "PRINT", "HALT"]
    assert program.constants[0] is True


def test_fold_not(mv):
    program = mv.compile_source("print not false;", optimize=True)
    assert [i.op for i in program.instructions] == ["CONST", "PRINT", "HALT"]


def test_fold_unary_minus(mv):
    program = mv.compile_source("print -(2 + 3);", optimize=True)
    assert [i.op for i in program.instructions] == ["CONST", "PRINT", "HALT"]
    assert program.constants[0] == -5


def test_division_by_zero_never_folded(mv, run):
    with pytest.raises(mv.VMRuntimeError):
        run("print 1 / 0;", optimize=True)


def test_modulo_by_zero_never_folded(mv, run):
    with pytest.raises(mv.VMRuntimeError):
        run("print 1 % 0;", optimize=True)


def test_type_error_never_folded(mv, run):
    with pytest.raises(mv.VMRuntimeError):
        run('print "a" + 1;', optimize=True)


def test_true_and_x_not_folded_to_x(mv, run):
    with pytest.raises(mv.VMRuntimeError):
        run("let y = true and 5; print y;", optimize=True)


def test_false_or_x_not_folded_to_x(mv, run):
    with pytest.raises(mv.VMRuntimeError):
        run("let y = false or 5; print y;", optimize=True)


def test_false_and_x_safe(run):
    assert run("print false and (1 / 0 == 0);", optimize=True) == ["false"]


def test_true_or_x_safe(run):
    assert run("print true or (1 / 0 == 0);", optimize=True) == ["true"]


def test_both_literal_bools_fold(mv):
    program = mv.compile_source("print true and false;", optimize=True)
    assert [i.op for i in program.instructions] == ["CONST", "PRINT", "HALT"]


def test_fold_constants_is_callable(mv):
    assert callable(mv.fold_constants)


@pytest.mark.parametrize("src", [
    "let i = 0; while (i < 4) { print i * 3; i = i + 1; }",
    'if (1 + 1 == 2) { print "y"; } else { print "n"; }',
    "print not (1 > 2); print -(2 + 3); print 10 % 3;",
    'let s = "a" + "b"; print s + "c";',
    "let x = 2; if (x > 1 and x < 5) { print x * x; }",
])
def test_optimize_preserves_behaviour(run, src):
    assert run(src, optimize=True) == run(src)


# --------------------------------------------------------------------------- #
# 10. serializer
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("src", [
    "print 1;",
    'let x = 2; while (x > 0) { print "hi" + "!"; x = x - 1; }',
    "print 1.5; print true; print false;",
    'if (true) { print "a"; } else { print "b"; }',
])
def test_round_trip_behaviour(mv, src):
    program = mv.compile_source(src)
    again = mv.loads(mv.dumps(program))
    assert mv.execute(again) == mv.execute(program)


def test_round_trip_structure(mv):
    program = mv.compile_source('let a = 1; print a + 2.5; print "s";')
    again = mv.loads(mv.dumps(program))
    assert list(again.names) == list(program.names)
    assert list(again.constants) == list(program.constants)
    assert [(i.op, i.arg) for i in again.instructions] == [
        (i.op, i.arg) for i in program.instructions]


def test_round_trip_preserves_constant_types(mv):
    program = mv.compile_source("print 1; print 1.0; print true;")
    again = mv.loads(mv.dumps(program))
    assert [type(c) for c in again.constants] == [type(c) for c in program.constants]


def test_dumps_deterministic(mv):
    program = mv.compile_source("let x = 1; print x;")
    assert mv.dumps(program) == mv.dumps(program)


def test_magic_and_version_bytes(mv):
    data = mv.dumps(mv.compile_source("print 1;"))
    assert data[:4] == b"MVM1"
    assert data[4] == 1


def test_int_constant_encoding(mv):
    data = mv.dumps(mv.compile_source("print 300;"))
    assert struct.pack(">Bq", 0x01, 300) in data


def test_float_constant_encoding(mv):
    data = mv.dumps(mv.compile_source("print 1.5;"))
    assert struct.pack(">Bd", 0x02, 1.5) in data


def test_string_constant_encoding(mv):
    data = mv.dumps(mv.compile_source('print "hi";'))
    assert struct.pack(">BI", 0x03, 2) + b"hi" in data


def test_bool_constant_encoding(mv):
    data = mv.dumps(mv.compile_source("print true;"))
    assert struct.pack(">BB", 0x04, 1) in data


def test_no_arg_sentinel(mv):
    data = mv.dumps(mv.compile_source("print 1;"))
    assert b"\xff\xff\xff\xff" in data


def test_checksum_is_crc32_of_body(mv):
    data = mv.dumps(mv.compile_source("print 42;"))
    body, crc = data[4:-4], struct.unpack(">I", data[-4:])[0]
    assert crc == zlib.crc32(body)


def test_i64_overflow_raises(mv):
    program = mv.compile_source("print 1;")
    program.constants[0] = 2 ** 63
    with pytest.raises(mv.SerializationError):
        mv.dumps(program)
    program.constants[0] = -(2 ** 63) - 1
    with pytest.raises(mv.SerializationError):
        mv.dumps(program)


def test_i64_boundaries_ok(mv):
    program = mv.compile_source("print 1;")
    for value in (2 ** 63 - 1, -(2 ** 63)):
        program.constants[0] = value
        assert mv.loads(mv.dumps(program)).constants[0] == value


def test_bad_magic(mv):
    good = mv.dumps(mv.compile_source("print 1;"))
    with pytest.raises(mv.SerializationError):
        mv.loads(b"XXXX" + good[4:])


def test_empty_and_tiny_inputs(mv):
    for data in (b"", b"MVM1", b"MVM1\x01"):
        with pytest.raises(mv.SerializationError):
            mv.loads(data)


def test_corruption_anywhere_is_detected(mv):
    good = mv.dumps(mv.compile_source('let x = 1; print x + 2;'))
    for index in range(4, len(good)):
        bad = bytearray(good)
        bad[index] ^= 0xFF
        with pytest.raises(mv.SerializationError):
            mv.loads(bytes(bad))


def test_truncation_everywhere_is_detected(mv):
    good = mv.dumps(mv.compile_source("print 1;"))
    for end in range(len(good)):
        with pytest.raises(mv.SerializationError):
            mv.loads(good[:end])


def test_trailing_bytes_rejected(mv):
    good = mv.dumps(mv.compile_source("print 1;"))
    with pytest.raises(mv.SerializationError):
        mv.loads(good + b"\x00")


def _rebuild_with_crc(data: bytes, body: bytes) -> bytes:
    return data[:4] + body + struct.pack(">I", zlib.crc32(body))


def test_unknown_version_rejected(mv):
    good = mv.dumps(mv.compile_source("print 1;"))
    body = bytearray(good[4:-4])
    body[0] = 9
    with pytest.raises(mv.SerializationError):
        mv.loads(_rebuild_with_crc(good, bytes(body)))


def test_unknown_constant_tag_rejected(mv):
    good = mv.dumps(mv.compile_source("print true;"))
    body = bytearray(good[4:-4])
    index = body.index(bytes([0x04]))
    body[index] = 0x7E
    with pytest.raises(mv.SerializationError):
        mv.loads(_rebuild_with_crc(good, bytes(body)))


def test_bool_payload_must_be_zero_or_one(mv):
    good = mv.dumps(mv.compile_source("print true;"))
    body = bytearray(good[4:-4])
    index = body.index(struct.pack(">BB", 0x04, 1))
    body[index + 1] = 2
    with pytest.raises(mv.SerializationError):
        mv.loads(_rebuild_with_crc(good, bytes(body)))


def test_execute_after_loads(mv):
    program = mv.compile_source("let i = 0; while (i < 3) { print i; i = i + 1; }")
    assert mv.execute(mv.loads(mv.dumps(program))) == ["0", "1", "2"]


# --------------------------------------------------------------------------- #
# 11. disassembler
# --------------------------------------------------------------------------- #

def test_disassemble_exact_canonical(mv):
    assert mv.disassemble(mv.compile_source("print 1;")) == (
        "0000 CONST 0  ; 1\n0001 PRINT\n0002 HALT\n")


def test_disassemble_line_count(mv):
    program = mv.compile_source("let x = 1; print x + 2;")
    text = mv.disassemble(program)
    assert len(text.splitlines()) == len(program.instructions)
    assert text.endswith("\n")


def test_disassemble_indices_are_padded(mv):
    text = mv.disassemble(mv.compile_source("let x = 1; print x + 2;"))
    for index, line in enumerate(text.splitlines()):
        assert line.startswith(f"{index:04d} ")


def test_disassemble_const_comments(mv):
    text = mv.disassemble(mv.compile_source('print 1.5; print true; print "a\\nb";'))
    assert "; 1.5" in text
    assert "; true" in text
    assert '; "a\\nb"' in text


def test_disassemble_string_escapes_backslash_and_quote(mv):
    text = mv.disassemble(mv.compile_source(r'print "q\"w\\e";'))
    assert r'; "q\"w\\e"' in text


def test_disassemble_no_arg_ops_bare(mv):
    text = mv.disassemble(mv.compile_source("print 1;"))
    lines = text.splitlines()
    assert lines[1] == "0001 PRINT"
    assert lines[2] == "0002 HALT"


# --------------------------------------------------------------------------- #
# 12. package surface
# --------------------------------------------------------------------------- #

def test_all_exact(mv):
    assert sorted(mv.__all__) == sorted([
        "tokenize", "Token", "parse", "compile_source", "Program", "Instr",
        "fold_constants", "execute", "dumps", "loads", "disassemble",
        "OPCODES", "OPCODE_NUMBERS", "MicroVMError", "LexError", "ParseError",
        "CompileError", "SerializationError", "VMRuntimeError"])


def test_all_names_resolve(mv):
    for name in mv.__all__:
        assert getattr(mv, name) is not None


def test_error_hierarchy(mv):
    from microvm.errors import StepLimitError
    for name in ("LexError", "ParseError", "CompileError", "SerializationError",
                 "VMRuntimeError"):
        assert issubclass(getattr(mv, name), mv.MicroVMError)
    assert issubclass(StepLimitError, mv.VMRuntimeError)


def test_expected_modules_exist():
    for name in ("__init__", "errors", "opcodes", "lexer", "parser", "compiler",
                 "optimizer", "vm", "serializer", "disassembler", "__main__"):
        assert Path("microvm").joinpath(f"{name}.py").is_file(), name


def test_no_forbidden_modules():
    """Word-boundary match: `from .disassembler import disassemble` contains the
    substring `import dis` and must not count. Only the module names themselves
    are forbidden."""
    import re
    pattern = re.compile(r"^\s*(?:import|from)\s+(ast|dis|marshal|pickle|ctypes)", re.M)
    hits = []
    for path in Path(".").rglob("*.py"):
        if any(part in _IGNORED_DIRS for part in path.parts):
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for hit in pattern.finditer(text):
            hits.append(f"{path}: {hit.group(0).strip()}")
    assert hits == []


def test_no_eval_or_exec():
    hits = []
    for path in Path(".").rglob("*.py"):
        if any(part in _IGNORED_DIRS for part in path.parts):
            continue
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            for bad in ("eval(", "exec(", "compile("):
                at = stripped.find(bad)
                if at > 0 and (stripped[at - 1].isalnum() or stripped[at - 1] in "._"):
                    continue  # method call or longer name such as compile_source(
                if at >= 0:
                    hits.append(f"{path}: {stripped[:60]}")
    assert hits == []


# --------------------------------------------------------------------------- #
# 13. CLI
# --------------------------------------------------------------------------- #

@pytest.fixture
def source_file(tmp_path):
    def make(text, name="prog.mv"):
        path = tmp_path / name
        path.write_text(text, encoding="utf-8")
        return str(path)
    return make


def test_cli_run(source_file):
    done = cli("run", source_file("let x = 5; print x; print 8 / 2;"))
    assert done.returncode == 0
    assert done.stdout == "5\n4.0\n"


def test_cli_run_optimize_flag(source_file):
    done = cli("run", source_file("print 1 + 2 * 3;"), "--optimize")
    assert done.returncode == 0 and done.stdout == "7\n"


def test_cli_build_then_exec(source_file, tmp_path):
    out = str(tmp_path / "prog.mvb")
    assert cli("build", source_file('print "built";'), out).returncode == 0
    done = cli("exec", out)
    assert done.returncode == 0 and done.stdout == "built\n"


def test_cli_build_output_is_loadable(mv, source_file, tmp_path):
    out = tmp_path / "prog.mvb"
    cli("build", source_file("print 1;"), str(out))
    assert mv.execute(mv.loads(out.read_bytes())) == ["1"]


def test_cli_disasm(source_file, tmp_path):
    out = str(tmp_path / "prog.mvb")
    cli("build", source_file("print 1;"), out)
    done = cli("disasm", out)
    assert done.returncode == 0
    assert done.stdout == "0000 CONST 0  ; 1\n0001 PRINT\n0002 HALT\n"


@pytest.mark.parametrize("args", [(), ("frobnicate",), ("run",), ("build", "only-one"),
                                  ("exec",), ("disasm",)])
def test_cli_usage_exit_two(args):
    assert cli(*args).returncode == 2


def test_cli_missing_file_exit_two(tmp_path):
    assert cli("run", str(tmp_path / "missing.mv")).returncode == 2
    assert cli("exec", str(tmp_path / "missing.mvb")).returncode == 2


@pytest.mark.parametrize("value", ["0", "-3", "abc"])
def test_cli_bad_step_limit_exit_two(source_file, value):
    assert cli("run", source_file("print 1;"), "--step-limit", value).returncode == 2


@pytest.mark.parametrize("src", ["print @;", "print 1 < 2 < 3;", "let a = 1; let a = 2;",
                                 "print 1 / 0;", "print zz;"])
def test_cli_microvm_errors_exit_three(source_file, src):
    done = cli("run", source_file(src))
    assert done.returncode == 3
    assert done.stdout == ""
    assert done.stderr.strip() != ""


def test_cli_no_partial_output_on_runtime_error(source_file):
    done = cli("run", source_file('print "before"; print 1 / 0;'))
    assert done.returncode == 3 and done.stdout == ""


def test_cli_step_limit_flag_enforced(source_file):
    done = cli("run", source_file("while (true) {}"), "--step-limit", "50")
    assert done.returncode == 3


def test_cli_exec_corrupt_binary_exit_three(tmp_path):
    bad = tmp_path / "bad.mvb"
    bad.write_bytes(b"MVM1 this is not a program")
    assert cli("exec", str(bad)).returncode == 3


def test_cli_main_returns_int():
    module = importlib.import_module("microvm.__main__")
    assert callable(module.main)
