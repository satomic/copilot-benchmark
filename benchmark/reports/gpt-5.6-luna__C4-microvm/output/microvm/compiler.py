import dataclasses
from .parser import *
from .optimizer import fold_constants
from .opcodes import OPCODES
from .errors import CompileError


@dataclasses.dataclass(frozen=True)
class Instr:
    op: str
    arg: int | None = None


@dataclasses.dataclass
class Program:
    constants: list
    names: list[str]
    instructions: list[Instr]


class _Compiler:
    def __init__(self) -> None:
        self.p = Program([], [], [])
        self.declared: dict[str, int] = {}

    def emit(self, op: str, arg: int | None = None) -> int:
        if op not in OPCODES: raise CompileError("unknown opcode")
        return self.p.instructions.append(Instr(op, arg)) or len(self.p.instructions) - 1

    def const(self, value: object) -> int:
        for i, old in enumerate(self.p.constants):
            if type(old) is type(value) and old == value: return i
        self.p.constants.append(value); return len(self.p.constants) - 1

    def declare(self, node: object) -> None:
        if isinstance(node, Let):
            if node.name in self.declared:
                raise CompileError("duplicate declaration " + node.name)
            self.declared[node.name] = len(self.p.names)
            self.p.names.append(node.name)
            self.declare(node.expr)
        elif isinstance(node, (Assign, Print)):
            self.declare(node.expr)
        elif isinstance(node, Block):
            for item in node.statements:
                self.declare(item)
        elif isinstance(node, If):
            self.declare(node.cond)
            self.declare(node.then)
            if node.otherwise:
                self.declare(node.otherwise)
        elif isinstance(node, While):
            self.declare(node.cond)
            self.declare(node.body)

    def expr(self, node: object) -> None:
        if isinstance(node, Literal): self.emit("CONST", self.const(node.value)); return
        if isinstance(node, Variable):
            if node.name not in self.declared: raise CompileError("undeclared name " + node.name)
            self.emit("LOAD", self.declared[node.name]); return
        if isinstance(node, Unary):
            self.expr(node.expr); self.emit("NEG" if node.op == "-" else "NOT"); return
        if isinstance(node, Binary) and node.op in ("and", "or"):
            self.expr(node.left)
            if node.op == "and":
                left_false = self.emit("JUMP_IF_FALSE", 0)
                self.expr(node.right)
                right_false = self.emit("JUMP_IF_FALSE", 0)
                self.emit("CONST", self.const(True))
                done = self.emit("JUMP", 0)
                false_target = len(self.p.instructions)
                self.emit("CONST", self.const(False))
                end = len(self.p.instructions)
                self.p.instructions[left_false] = Instr("JUMP_IF_FALSE", false_target)
                self.p.instructions[right_false] = Instr("JUMP_IF_FALSE", false_target)
                self.p.instructions[done] = Instr("JUMP", end)
            else:
                jump_false = self.emit("JUMP_IF_FALSE", 0)
                true_left = self.emit("CONST", self.const(True))
                true_jump = self.emit("JUMP", 0)
                rhs = len(self.p.instructions)
                self.p.instructions[jump_false] = Instr("JUMP_IF_FALSE", rhs)
                self.expr(node.right)
                right_false = self.emit("JUMP_IF_FALSE", 0)
                true_right = self.emit("CONST", self.const(True))
                right_jump = self.emit("JUMP", 0)
                false_target = len(self.p.instructions)
                self.emit("CONST", self.const(False))
                end = len(self.p.instructions)
                self.p.instructions[right_false] = Instr("JUMP_IF_FALSE", false_target)
                self.p.instructions[true_jump] = Instr("JUMP", end)
                self.p.instructions[right_jump] = Instr("JUMP", end)
            return
        if isinstance(node, Binary):
            self.expr(node.left); self.expr(node.right); self.emit({"+" : "ADD", "-" : "SUB", "*" : "MUL", "/" : "DIV", "%" : "MOD",
                "==" : "EQ", "!=" : "NE", "<" : "LT", "<=" : "LE", ">" : "GT", ">=" : "GE"}[node.op]); return
        raise CompileError("bad expression")

    def stmt(self, node: object) -> None:
        if isinstance(node, Let):
            self.expr(node.expr); self.emit("STORE", self.declared[node.name]); return
        if isinstance(node, Assign):
            if node.name not in self.declared: raise CompileError("undeclared name " + node.name)
            self.expr(node.expr); self.emit("STORE", self.declared[node.name]); return
        if isinstance(node, Print): self.expr(node.expr); self.emit("PRINT"); return
        if isinstance(node, Block):
            for x in node.statements: self.stmt(x)
            return
        if isinstance(node, If):
            self.expr(node.cond); jf = self.emit("JUMP_IF_FALSE", 0); self.stmt(node.then)
            if node.otherwise:
                jend = self.emit("JUMP", 0); self.p.instructions[jf] = Instr("JUMP_IF_FALSE", len(self.p.instructions)); self.stmt(node.otherwise)
                self.p.instructions[jend] = Instr("JUMP", len(self.p.instructions))
            else: self.p.instructions[jf] = Instr("JUMP_IF_FALSE", len(self.p.instructions))
            return
        if isinstance(node, While):
            begin = len(self.p.instructions); self.expr(node.cond); jf = self.emit("JUMP_IF_FALSE", 0); self.stmt(node.body)
            self.emit("JUMP", begin); self.p.instructions[jf] = Instr("JUMP_IF_FALSE", len(self.p.instructions)); return
        raise CompileError("bad statement")


def compile_source(src: str, *, optimize: bool = False) -> Program:
    tree = parse(src)
    if optimize: tree = fold_constants(tree)
    c = _Compiler()
    for stmt in tree.statements: c.declare(stmt)
    for stmt in tree.statements: c.stmt(stmt)
    c.emit("HALT")
    return c.p
