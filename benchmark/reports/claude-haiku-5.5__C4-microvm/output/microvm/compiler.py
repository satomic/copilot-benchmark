"""Bytecode generation: scope checking, slot allocation and code emission."""

from __future__ import annotations

import dataclasses

from .errors import CompileError
from .optimizer import fold_constants
from .parser import (
    Assign, Binary, Block, If, Let, Literal, Logical, Name, Print, Unary, While, parse,
)

_BINARY_OPCODES: dict[str, str] = {
    "+": "ADD", "-": "SUB", "*": "MUL", "/": "DIV", "%": "MOD",
    "==": "EQ", "!=": "NE", "<": "LT", "<=": "LE", ">": "GT", ">=": "GE",
}
_UNARY_OPCODES: dict[str, str] = {"-": "NEG", "not": "NOT"}


@dataclasses.dataclass(frozen=True)
class Instr:
    op: str
    arg: int | None  # None exactly when the opcode takes no argument


@dataclasses.dataclass
class Program:
    constants: list
    names: list[str]
    instructions: list


class _Scope:
    """Checks declarations in source order and assigns variable slots."""

    def __init__(self) -> None:
        self.names: list[str] = []
        self.slots: dict[str, int] = {}

    def declare(self, name: str) -> None:
        if name in self.slots:
            raise CompileError(f"variable '{name}' is already declared")
        self.slots[name] = len(self.names)
        self.names.append(name)

    def require(self, name: str) -> None:
        if name not in self.slots:
            raise CompileError(f"variable '{name}' is not declared")

    def check_stmt(self, node: object) -> None:
        if isinstance(node, Block):
            for stmt in node.stmts:
                self.check_stmt(stmt)
        elif isinstance(node, Let):
            self.check_expr(node.value)
            self.declare(node.name)
        elif isinstance(node, Assign):
            self.check_expr(node.value)
            self.require(node.name)
        elif isinstance(node, Print):
            self.check_expr(node.value)
        elif isinstance(node, If):
            self.check_expr(node.cond)
            self.check_stmt(node.then_body)
            if node.else_body is not None:
                self.check_stmt(node.else_body)
        elif isinstance(node, While):
            self.check_expr(node.cond)
            self.check_stmt(node.body)

    def check_expr(self, node: object) -> None:
        if isinstance(node, Name):
            self.require(node.name)
        elif isinstance(node, Unary):
            self.check_expr(node.operand)
        elif isinstance(node, (Binary, Logical)):
            self.check_expr(node.left)
            self.check_expr(node.right)


class _CodeGen:
    """Emits instructions for a checked, optionally folded AST."""

    def __init__(self, slots: dict[str, int]) -> None:
        self.slots = slots
        self.constants: list[object] = []
        self.code: list[Instr] = []
        self._pool: dict[tuple[str, str], int] = {}

    def emit(self, op: str, arg: int | None = None) -> int:
        self.code.append(Instr(op, arg))
        return len(self.code) - 1

    def patch(self, index: int, target: int) -> None:
        self.code[index] = Instr(self.code[index].op, target)

    def here(self) -> int:
        return len(self.code)

    def const_index(self, value: object) -> int:
        # repr distinguishes 0.0 from -0.0 and 1 from True; the type name separates 1 from 1.0.
        key = (type(value).__name__, repr(value))
        if key not in self._pool:
            self._pool[key] = len(self.constants)
            self.constants.append(value)
        return self._pool[key]

    def emit_const(self, value: object) -> None:
        self.emit("CONST", self.const_index(value))

    def stmt(self, node: object) -> None:
        if isinstance(node, Block):
            for item in node.stmts:
                self.stmt(item)
        elif isinstance(node, (Let, Assign)):
            self.expr(node.value)
            self.emit("STORE", self.slots[node.name])
        elif isinstance(node, Print):
            self.expr(node.value)
            self.emit("PRINT")
        elif isinstance(node, If):
            self.if_stmt(node)
        elif isinstance(node, While):
            self.while_stmt(node)

    def if_stmt(self, node: If) -> None:
        self.expr(node.cond)
        to_else = self.emit("JUMP_IF_FALSE", 0)
        self.stmt(node.then_body)
        if node.else_body is None:
            self.patch(to_else, self.here())
            return
        to_end = self.emit("JUMP", 0)
        self.patch(to_else, self.here())
        self.stmt(node.else_body)
        self.patch(to_end, self.here())

    def while_stmt(self, node: While) -> None:
        start = self.here()
        self.expr(node.cond)
        to_end = self.emit("JUMP_IF_FALSE", 0)
        self.stmt(node.body)
        self.emit("JUMP", start)
        self.patch(to_end, self.here())

    def expr(self, node: object) -> None:
        if isinstance(node, Literal):
            self.emit_const(node.value)
        elif isinstance(node, Name):
            self.emit("LOAD", self.slots[node.name])
        elif isinstance(node, Unary):
            self.expr(node.operand)
            self.emit(_UNARY_OPCODES[node.op])
        elif isinstance(node, Binary):
            self.expr(node.left)
            self.expr(node.right)
            self.emit(_BINARY_OPCODES[node.op])
        elif isinstance(node, Logical):
            self.logical(node)

    def logical(self, node: Logical) -> None:
        # NOT NOT re-checks that the operand is BOOL and leaves its value unchanged.
        self.expr(node.left)
        to_false_path = self.emit("JUMP_IF_FALSE", 0)
        if node.op == "and":
            self.expr(node.right)
            self.emit("NOT")
            self.emit("NOT")
            to_end = self.emit("JUMP", 0)
            self.patch(to_false_path, self.here())
            self.emit_const(False)
        else:
            self.emit_const(True)
            to_end = self.emit("JUMP", 0)
            self.patch(to_false_path, self.here())
            self.expr(node.right)
            self.emit("NOT")
            self.emit("NOT")
        self.patch(to_end, self.here())


def compile_source(src: str, *, optimize: bool = False) -> Program:
    """Compile MicroVM source into a Program.

    Scope checks run on the unfolded AST so that folding cannot hide a CompileError.
    """
    tree = parse(src)
    scope = _Scope()
    scope.check_stmt(tree)
    if optimize:
        tree = fold_constants(tree)
    gen = _CodeGen(scope.slots)
    gen.stmt(tree)
    gen.emit("HALT")
    return Program(constants=gen.constants, names=scope.names, instructions=gen.code)
