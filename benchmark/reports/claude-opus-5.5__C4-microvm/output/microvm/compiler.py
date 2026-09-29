"""Code generation from the AST to stack-machine bytecode."""

from __future__ import annotations

import dataclasses
import struct
from typing import Iterator, Optional

from .errors import CompileError
from .opcodes import BINARY_OPCODES, UNARY_OPCODES
from .optimizer import fold_constants
from .parser import (
    Assign, Binary, Block, If, Let, Literal, Module, Name, Print, Unary, While,
    deep_recursion, parse,
)


@dataclasses.dataclass(frozen=True)
class Instr:
    op: str
    arg: Optional[int]


@dataclasses.dataclass
class Program:
    constants: list
    names: list[str]
    instructions: list


def _children(node: object) -> Iterator[object]:
    for field in dataclasses.fields(node):
        value = getattr(node, field.name)
        items = value if isinstance(value, tuple) else (value,)
        for item in items:
            if dataclasses.is_dataclass(item):
                yield item


def _walk(node: object) -> Iterator[object]:
    """Yield every AST node in source (pre-)order, without recursion."""
    stack = [node]
    while stack:
        current = stack.pop()
        yield current
        stack.extend(reversed(list(_children(current))))


def _resolve_names(tree: Module) -> list[str]:
    # Blocks do not create scope and a `let` declares its name for the whole
    # program, so declarations are collected up front (slot order = source order)
    # and a read before the `let` executes is a run-time error, not a compile error.
    names: list[str] = []
    for node in _walk(tree):
        if isinstance(node, Let):
            if node.name in names:
                raise CompileError(f"variable '{node.name}' declared twice")
            names.append(node.name)
    declared = set(names)
    for node in _walk(tree):
        if isinstance(node, (Name, Assign)) and node.name not in declared:
            raise CompileError(f"variable '{node.name}' is not declared")
    return names


def _constant_key(value: object) -> tuple:
    if type(value) is float:
        # Keyed by bit pattern so 0.0 / -0.0 and NaN are kept faithfully.
        return ("FLOAT", struct.pack(">d", value))
    return (type(value).__name__, value)


class _CodeGen:
    def __init__(self, names: list[str]) -> None:
        self.names = names
        self.slots = {name: index for index, name in enumerate(names)}
        self.constants: list = []
        self.const_index: dict[tuple, int] = {}
        self.code: list[Instr] = []

    def emit(self, op: str, arg: Optional[int] = None) -> int:
        self.code.append(Instr(op, arg))
        return len(self.code) - 1

    def patch(self, index: int) -> None:
        """Point the jump at ``index`` to the next instruction to be emitted."""
        self.code[index] = Instr(self.code[index].op, len(self.code))

    def constant(self, value: object) -> None:
        key = _constant_key(value)
        if key not in self.const_index:
            self.const_index[key] = len(self.constants)
            self.constants.append(value)
        self.emit("CONST", self.const_index[key])

    def statement(self, node: object) -> None:
        if isinstance(node, (Let, Assign)):
            self.expression(node.value)
            self.emit("STORE", self.slots[node.name])
        elif isinstance(node, Print):
            self.expression(node.value)
            self.emit("PRINT")
        elif isinstance(node, (Block, Module)):
            for child in node.body:
                self.statement(child)
        elif isinstance(node, If):
            self.if_statement(node)
        elif isinstance(node, While):
            start = len(self.code)
            self.expression(node.cond)
            exit_jump = self.emit("JUMP_IF_FALSE", 0)
            self.statement(node.body)
            self.emit("JUMP", start)
            self.patch(exit_jump)
        else:
            raise CompileError(f"unknown statement node {type(node).__name__}")

    def if_statement(self, node: If) -> None:
        self.expression(node.cond)
        else_jump = self.emit("JUMP_IF_FALSE", 0)
        self.statement(node.then)
        if node.orelse is None:
            self.patch(else_jump)
            return
        end_jump = self.emit("JUMP", 0)
        self.patch(else_jump)
        self.statement(node.orelse)
        self.patch(end_jump)

    def expression(self, node: object) -> None:
        if isinstance(node, Literal):
            self.constant(node.value)
        elif isinstance(node, Name):
            self.emit("LOAD", self.slots[node.name])
        elif isinstance(node, Unary):
            self.expression(node.operand)
            self.emit(UNARY_OPCODES[node.op])
        elif isinstance(node, Binary) and node.op in ("and", "or"):
            self.logical(node)
        elif isinstance(node, Binary):
            self.expression(node.left)
            self.expression(node.right)
            self.emit(BINARY_OPCODES[node.op])
        else:
            raise CompileError(f"unknown expression node {type(node).__name__}")

    def logical(self, node: Binary) -> None:
        # and: L; JIF short; R; NOT; NOT; JUMP end; short: CONST false; end:
        # or:  L; JIF long; CONST true; JUMP end; long: R; NOT; NOT; end:
        # JUMP_IF_FALSE checks that L is BOOL; NOT NOT checks R is BOOL, keeping it.
        self.expression(node.left)
        branch = self.emit("JUMP_IF_FALSE", 0)
        if node.op == "and":
            self.checked_bool(node.right)
            end = self.emit("JUMP", 0)
            self.patch(branch)
            self.constant(False)
        else:
            self.constant(True)
            end = self.emit("JUMP", 0)
            self.patch(branch)
            self.checked_bool(node.right)
        self.patch(end)

    def checked_bool(self, node: object) -> None:
        self.expression(node)
        self.emit("NOT")
        self.emit("NOT")


def compile_source(src: str, *, optimize: bool = False) -> Program:
    """Compile source text into a ``Program``."""
    tree = parse(src)
    names = _resolve_names(tree)
    try:
        with deep_recursion():
            if optimize:
                tree = fold_constants(tree)
            gen = _CodeGen(names)
            gen.statement(tree)
    except RecursionError:
        raise CompileError("program is nested too deeply") from None
    gen.emit("HALT")
    return Program(constants=gen.constants, names=list(names), instructions=gen.code)
