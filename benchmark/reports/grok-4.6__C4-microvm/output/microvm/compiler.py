from __future__ import annotations

from dataclasses import dataclass

from microvm.errors import CompileError
from microvm.opcodes import HAS_ARG, OPCODES
from microvm.optimizer import fold_constants
from microvm.parser import (
    Assign,
    Binary,
    Block,
    If,
    Let,
    Literal,
    Name,
    Print,
    Script,
    Unary,
    While,
    parse,
)

_BIN_OPS: dict[str, str] = {
    "+": "ADD",
    "-": "SUB",
    "*": "MUL",
    "/": "DIV",
    "%": "MOD",
    "==": "EQ",
    "!=": "NE",
    "<": "LT",
    "<=": "LE",
    ">": "GT",
    ">=": "GE",
}


@dataclass(frozen=True)
class Instr:
    op: str
    arg: int | None


@dataclass
class Program:
    constants: list[object]
    names: list[str]
    instructions: list[Instr]


def compile_source(src: str, *, optimize: bool = False) -> Program:
    tree = parse(src)
    if optimize:
        tree = fold_constants(tree)
    gen = _Gen()
    gen.collect(tree)
    gen.compile(tree)
    gen.emit("HALT")
    return Program(gen.constants, gen.names, gen.ins)


class _Gen:
    def __init__(self) -> None:
        self.constants: list[object] = []
        self._const_key: dict[tuple[type, object], int] = {}
        self.names: list[str] = []
        self._name_slot: dict[str, int] = {}
        self.ins: list[Instr] = []

    def emit(self, op: str, arg: int | None = None) -> int:
        if op not in OPCODES:
            raise CompileError(f"unknown opcode {op}")
        if (op in HAS_ARG) != (arg is not None):
            raise CompileError(f"bad argument for {op}")
        self.ins.append(Instr(op, arg))
        return len(self.ins) - 1

    def add_const(self, value: object) -> int:
        key = (type(value), value)
        idx = self._const_key.get(key)
        if idx is None:
            idx = len(self.constants)
            self._const_key[key] = idx
            self.constants.append(value)
        return idx

    def slot(self, name: str) -> int:
        if name not in self._name_slot:
            raise CompileError(f"undeclared name {name}")
        return self._name_slot[name]

    def collect(self, node: object) -> None:
        if isinstance(node, (Script, Block)):
            for stmt in node.statements:
                self.collect(stmt)
        elif isinstance(node, Let):
            self._declare(node.name)
            self.collect(node.expr)
        elif isinstance(node, (Assign, Print)):
            self.collect(node.expr)
        elif isinstance(node, If):
            self.collect(node.cond)
            self.collect(node.then_body)
            if node.else_body is not None:
                self.collect(node.else_body)
        elif isinstance(node, While):
            self.collect(node.cond)
            self.collect(node.body)
        elif isinstance(node, Binary):
            self.collect(node.left)
            self.collect(node.right)
        elif isinstance(node, Unary):
            self.collect(node.expr)

    def _declare(self, name: str) -> None:
        if name in self._name_slot:
            raise CompileError(f"duplicate declaration of {name}")
        self._name_slot[name] = len(self.names)
        self.names.append(name)

    def compile(self, node: object) -> None:
        if isinstance(node, Script):
            for stmt in node.statements:
                self.compile(stmt)
        elif isinstance(node, Block):
            for stmt in node.statements:
                self.compile(stmt)
        elif isinstance(node, Let):
            self.compile(node.expr)
            self.emit("STORE", self.slot(node.name))
        elif isinstance(node, Assign):
            self.compile(node.expr)
            self.emit("STORE", self.slot(node.name))
        elif isinstance(node, Print):
            self.compile(node.expr)
            self.emit("PRINT")
        elif isinstance(node, If):
            self._compile_if(node)
        elif isinstance(node, While):
            self._compile_while(node)
        else:
            self.compile_expr(node)

    def compile_expr(self, node: object) -> None:
        if isinstance(node, Literal):
            self.emit("CONST", self.add_const(node.value))
        elif isinstance(node, Name):
            self.emit("LOAD", self.slot(node.name))
        elif isinstance(node, Unary):
            self.compile_expr(node.expr)
            self.emit("NEG" if node.op == "-" else "NOT")
        elif isinstance(node, Binary):
            self._compile_binary(node)
        else:
            raise CompileError("invalid expression")

    def _compile_binary(self, node: Binary) -> None:
        if node.op == "and":
            self._compile_and(node)
            return
        if node.op == "or":
            self._compile_or(node)
            return
        self.compile_expr(node.left)
        self.compile_expr(node.right)
        self.emit(_BIN_OPS[node.op])

    def _compile_and(self, node: Binary) -> None:
        # JUMP_IF_FALSE pops; restore false when skipping the right operand.
        self.compile_expr(node.left)
        jfalse = self.emit("JUMP_IF_FALSE", 0)
        self.compile_expr(node.right)
        self.emit("NOT")
        self.emit("NOT")
        jend = self.emit("JUMP", 0)
        self.ins[jfalse] = Instr("JUMP_IF_FALSE", len(self.ins))
        self.emit("CONST", self.add_const(False))
        self.ins[jend] = Instr("JUMP", len(self.ins))

    def _compile_or(self, node: Binary) -> None:
        self.compile_expr(node.left)
        jfalse = self.emit("JUMP_IF_FALSE", 0)
        self.emit("CONST", self.add_const(True))
        jend = self.emit("JUMP", 0)
        self.ins[jfalse] = Instr("JUMP_IF_FALSE", len(self.ins))
        self.compile_expr(node.right)
        self.emit("NOT")
        self.emit("NOT")
        self.ins[jend] = Instr("JUMP", len(self.ins))

    def _compile_if(self, node: If) -> None:
        self.compile_expr(node.cond)
        jfalse = self.emit("JUMP_IF_FALSE", 0)
        self.compile(node.then_body)
        if node.else_body is None:
            self.ins[jfalse] = Instr("JUMP_IF_FALSE", len(self.ins))
            return
        jend = self.emit("JUMP", 0)
        self.ins[jfalse] = Instr("JUMP_IF_FALSE", len(self.ins))
        self.compile(node.else_body)
        self.ins[jend] = Instr("JUMP", len(self.ins))

    def _compile_while(self, node: While) -> None:
        start = len(self.ins)
        self.compile_expr(node.cond)
        jfalse = self.emit("JUMP_IF_FALSE", 0)
        self.compile(node.body)
        self.emit("JUMP", start)
        self.ins[jfalse] = Instr("JUMP_IF_FALSE", len(self.ins))
