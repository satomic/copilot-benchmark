import subprocess
import sys
import pytest
import microvm
from microvm.errors import *
from microvm.compiler import Program, Instr


def run(src, **kw):
    limit = kw.pop("step_limit", 100000)
    return microvm.execute(microvm.compile_source(src, **kw), step_limit=limit)
def test_01_int(): assert run("print 2+3;") == ["5"]
def test_02_float(): assert run("print 4/2;") == ["2.0"]
def test_03_string(): assert run('print "a";') == ["a"]
def test_04_bool(): assert run("print true;") == ["true"]
def test_05_sub(): assert run("print 5-2;") == ["3"]
def test_06_mul(): assert run("print 3*2;") == ["6"]
def test_07_mod(): assert run("print -7%3;") == ["2"]
def test_08_concat(): assert run('print "a"+"b";') == ["ab"]
def test_09_precedence(): assert run("print 2+3*4;") == ["14"]
def test_10_parentheses(): assert run("print (2+3)*4;") == ["20"]
def test_11_variables(): assert run("let x=2; x=x+1; print x;") == ["3"]
def test_12_if(): assert run('if (true) { print "yes"; } else { print "no"; }') == ["yes"]
def test_13_else_if(): assert run('if (false) { print 1; } else if (true) { print 2; }') == ["2"]
def test_14_while(): assert run("let x=3; while (x>0) { print x; x=x-1; }") == ["3","2","1"]
def test_15_block_global(): assert run("if (true) { let x=4; } print x;") == ["4"]
def test_16_not(): assert run("print not false;") == ["true"]
def test_17_and(): assert run("print true and false;") == ["false"]
def test_18_or(): assert run("print false or true;") == ["true"]
def test_19_eq(): assert run("print 1==1.0;") == ["true"]
def test_20_ne(): assert run("print true!=1;") == ["true"]
def test_21_lt(): assert run("print 1<2;") == ["true"]
def test_22_le(): assert run("print 2<=2;") == ["true"]
def test_23_gt(): assert run("print 2>1;") == ["true"]
def test_24_ge(): assert run("print 2>=2;") == ["true"]
def test_25_comments(): assert run("// hi\nprint 1;") == ["1"]
def test_26_escapes(): assert run(r'print "a\n\t\\";') == ["a\n\t\\"]
def test_27_lex_float(): assert microvm.tokenize("1.5e2")[0].value == 150.0
def test_28_lex_bad(): 
    with pytest.raises(LexError): microvm.tokenize("1.")
def test_29_parse_bad():
    with pytest.raises(ParseError): microvm.parse("print 1")
def test_30_compare_nonassoc():
    with pytest.raises(ParseError): microvm.parse("print 1<2<3;")
def test_31_duplicate():
    with pytest.raises(CompileError): microvm.compile_source("let x=1; let x=2;")
def test_32_undeclared():
    with pytest.raises(CompileError): microvm.compile_source("print x;")
def test_33_unassigned():
    with pytest.raises(VMRuntimeError): run("if (false) { let x=1; } print x;")
def test_34_short_and():
    assert run("print false and (1/0==0);") == ["false"]
def test_35_short_or():
    assert run("print true or (1/0==0);") == ["true"]
def test_36_strict_and():
    with pytest.raises(VMRuntimeError): run("print true and 5;")
def test_37_condition_type():
    with pytest.raises(VMRuntimeError): run("if (1) { print 1; }")
def test_38_arithmetic_type():
    with pytest.raises(VMRuntimeError): run('print "a"+1;')
def test_39_divzero():
    with pytest.raises(VMRuntimeError): run("print 1/0;")
def test_40_modzero():
    with pytest.raises(VMRuntimeError): run("print 1%0;")
def test_41_comparison_type():
    with pytest.raises(VMRuntimeError): run('print "a"<1;')
def test_42_pool_types():
    p = microvm.compile_source("print 1; print 1.0; print true; print 1;")
    assert p.constants == [1, 1.0, True]
def test_43_fold():
    assert len(microvm.compile_source("print 1+2*3;", optimize=True).instructions) == 3
def test_44_fold_divzero():
    with pytest.raises(VMRuntimeError): run("print 1/0;", optimize=True)
def test_45_fold_strict():
    with pytest.raises(VMRuntimeError): run("print true and 5;", optimize=True)
def test_46_roundtrip():
    p = microvm.compile_source("print 1;"); assert microvm.execute(microvm.loads(microvm.dumps(p))) == ["1"]
def test_47_corrupt_magic():
    with pytest.raises(SerializationError): microvm.loads(b"XXXX")
def test_48_corrupt_checksum():
    data = bytearray(microvm.dumps(microvm.compile_source("print 1;"))); data[-1] ^= 1
    with pytest.raises(SerializationError): microvm.loads(bytes(data))
def test_49_corrupt_trailing():
    with pytest.raises(SerializationError): microvm.loads(microvm.dumps(microvm.compile_source("print 1;")) + b"x")
def test_50_disasm():
    assert microvm.disassemble(microvm.compile_source("print 1;")) == "0000 CONST 0  ; 1\n0001 PRINT\n0002 HALT\n"
def test_51_step_limit():
    with pytest.raises(StepLimitError): run("while (true) {}", step_limit=10)
def test_52_bad_limit():
    with pytest.raises(ValueError): run("print 1;", step_limit=True)
def test_53_cli_run(tmp_path):
    f = tmp_path / "x.mv"; f.write_text("print 5;")
    r = subprocess.run([sys.executable, "-m", "microvm", "run", str(f)], capture_output=True, text=True)
    assert r.returncode == 0 and r.stdout == "5\n"
def test_54_cli_error(tmp_path):
    f = tmp_path / "x.mv"; f.write_text("print 1/0;")
    r = subprocess.run([sys.executable, "-m", "microvm", "run", str(f)], capture_output=True, text=True)
    assert r.returncode == 3 and r.stdout == ""
def test_55_cli_build_exec(tmp_path):
    src, binf = tmp_path / "x.mv", tmp_path / "x.bin"; src.write_text("print 7;")
    assert subprocess.run([sys.executable, "-m", "microvm", "build", str(src), str(binf)]).returncode == 0
    r = subprocess.run([sys.executable, "-m", "microvm", "exec", str(binf)], capture_output=True, text=True)
    assert r.returncode == 0 and r.stdout == "7\n"
