"""AST to bytecode. Forward jumps go through one patch point, _Emitter.patch."""

from __future__ import annotations

import dataclasses

from .errors import CompileError
from .opcodes import HAS_ARG, OPCODES
from .optimizer import fold_constants
from .parser import (
    Assign, Binary, Block, If, Let, Literal, Logical, Module, Name, NotOp,
    Print, Unary, While, parse,
)

__all__ = ["Instr", "Program", "compile_source"]

_BINARY_OPS = {"+": "ADD", "-": "SUB", "*": "MUL", "/": "DIV", "%": "MOD",
               "==": "EQ", "!=": "NE", "<": "LT", "<=": "LE", ">": "GT", ">=": "GE"}


@dataclasses.dataclass(frozen=True)
class Instr:
    op: str
    arg: int | None


@dataclasses.dataclass
class Program:
    constants: list
    names: list[str]
    instructions: list


class _Emitter:
    """Instruction buffer. All jump targets are patched here and nowhere else."""

    def __init__(self) -> None:
        self.instructions: list[Instr] = []
        self.constants: list = []
        self._pool: dict[tuple[type, object], int] = {}

    def emit(self, op: str, arg: int | None = None) -> int:
        assert (arg is not None) == (op in HAS_ARG) and op in OPCODES
        self.instructions.append(Instr(op, arg))
        return len(self.instructions) - 1

    def patch(self, at: int, target: int) -> None:
        self.instructions[at] = Instr(self.instructions[at].op, target)

    def here(self) -> int:
        return len(self.instructions)

    def const(self, value: object) -> int:
        """Pool index for ``value``, deduplicated by type and value together."""
        key = (type(value), value)
        if key not in self._pool:
            self._pool[key] = len(self.constants)
            self.constants.append(value)
        return self._pool[key]


class _Compiler:
    def __init__(self) -> None:
        self.emitter = _Emitter()
        self.slots: dict[str, int] = {}

    # -- statements -----------------------------------------------------------

    def statement(self, node: object) -> None:
        if isinstance(node, (Module, Block)):
            for child in node.statements:
                self.statement(child)
        elif isinstance(node, Let):
            if node.name in self.slots:
                raise CompileError(f"name {node.name!r} is already declared")
            self.slots[node.name] = len(self.slots)
            self.expr(node.expr)
            self.emitter.emit("STORE", self.slots[node.name])
        elif isinstance(node, Assign):
            if node.name not in self.slots:
                raise CompileError(f"assignment to undeclared name {node.name!r}")
            self.expr(node.expr)
            self.emitter.emit("STORE", self.slots[node.name])
        elif isinstance(node, Print):
            self.expr(node.expr)
            self.emitter.emit("PRINT")
        elif isinstance(node, If):
            self._if(node)
        elif isinstance(node, While):
            self._while(node)
        else:  # pragma: no cover - the parser produces nothing else
            raise CompileError(f"cannot compile {node!r}")

    def _if(self, node: If) -> None:
        self.expr(node.cond)
        to_else = self.emitter.emit("JUMP_IF_FALSE", 0)
        self.statement(node.then)
        if node.orelse is None:
            self.emitter.patch(to_else, self.emitter.here())
            return
        to_end = self.emitter.emit("JUMP", 0)
        self.emitter.patch(to_else, self.emitter.here())
        self.statement(node.orelse)
        self.emitter.patch(to_end, self.emitter.here())

    def _while(self, node: While) -> None:
        top = self.emitter.here()
        self.expr(node.cond)
        to_end = self.emitter.emit("JUMP_IF_FALSE", 0)
        self.statement(node.body)
        self.emitter.emit("JUMP", top)
        self.emitter.patch(to_end, self.emitter.here())

    # -- expressions ----------------------------------------------------------

    def expr(self, node: object) -> None:
        if isinstance(node, Literal):
            self.emitter.emit("CONST", self.emitter.const(node.value))
        elif isinstance(node, Name):
            if node.name not in self.slots:
                raise CompileError(f"undeclared name {node.name!r}")
            self.emitter.emit("LOAD", self.slots[node.name])
        elif isinstance(node, Unary):
            self.expr(node.operand)
            self.emitter.emit("NEG")
        elif isinstance(node, NotOp):
            self.expr(node.operand)
            self.emitter.emit("NOT")
        elif isinstance(node, Binary):
            self.expr(node.left)
            self.expr(node.right)
            self.emitter.emit(_BINARY_OPS[node.op])
        elif isinstance(node, Logical):
            self._logical(node)
        else:  # pragma: no cover
            raise CompileError(f"cannot compile expression {node!r}")

    def _logical(self, node: Logical) -> None:
        """Short-circuit via jumps.

        The kept operand still has to be BOOL, so it is passed through NOT twice:
        double negation is the identity on booleans and a VMRuntimeError on
        everything else, which is exactly the check the spec asks for.
        """
        self.expr(node.left)
        if node.op == "and":
            to_false = self.emitter.emit("JUMP_IF_FALSE", 0)
            self.expr(node.right)
            self.emitter.emit("NOT")
            self.emitter.emit("NOT")
            to_end = self.emitter.emit("JUMP", 0)
            self.emitter.patch(to_false, self.emitter.here())
            self.emitter.emit("CONST", self.emitter.const(False))
            self.emitter.patch(to_end, self.emitter.here())
        else:
            to_right = self.emitter.emit("JUMP_IF_FALSE", 0)
            self.emitter.emit("CONST", self.emitter.const(True))
            to_end = self.emitter.emit("JUMP", 0)
            self.emitter.patch(to_right, self.emitter.here())
            self.expr(node.right)
            self.emitter.emit("NOT")
            self.emitter.emit("NOT")
            self.emitter.patch(to_end, self.emitter.here())


def compile_source(src: str, *, optimize: bool = False) -> Program:
    """Compile ``src``; with ``optimize`` the AST is constant-folded first."""
    tree = parse(src)
    if optimize:
        tree = fold_constants(tree)
    compiler = _Compiler()
    compiler.statement(tree)
    compiler.emitter.emit("HALT")
    names = [None] * len(compiler.slots)
    for name, slot in compiler.slots.items():
        names[slot] = name
    return Program(compiler.emitter.constants, list(names), compiler.emitter.instructions)
