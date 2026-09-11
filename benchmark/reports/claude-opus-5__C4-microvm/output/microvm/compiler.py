"""Code generator turning the AST into a :class:`Program` of bytecode."""

from __future__ import annotations

import dataclasses

from . import parser as ast
from .errors import CompileError
from .opcodes import has_argument
from .optimizer import fold_constants
from .parser import parse

_BINARY_OPCODES: dict[str, str] = {
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


@dataclasses.dataclass(frozen=True)
class Instr:
    """A single bytecode instruction."""

    op: str
    arg: int | None


@dataclasses.dataclass
class Program:
    """A compiled program: constant pool, variable names and instructions."""

    constants: list
    names: list[str]
    instructions: list


def _collect_declarations(node: object, names: list[str]) -> None:
    """Collect ``let`` declarations in textual order.

    Blocks do not create scope, so a single flat list of slots is enough; the
    whole program is scanned first, which also makes a ``let`` in a branch that
    never runs declare its name.
    """
    if isinstance(node, ast.Let):
        if node.identifier in names:
            raise CompileError(f"variable {node.identifier!r} declared twice")
        names.append(node.identifier)
    elif isinstance(node, (ast.Module, ast.Block)):
        for statement in node.statements:
            _collect_declarations(statement, names)
    elif isinstance(node, ast.If):
        _collect_declarations(node.then_branch, names)
        if node.else_branch is not None:
            _collect_declarations(node.else_branch, names)
    elif isinstance(node, ast.While):
        _collect_declarations(node.body, names)


class _Compiler:
    """Accumulates constants and instructions while walking the AST."""

    def __init__(self, names: list[str]) -> None:
        self.names: list[str] = names
        self.slots: dict[str, int] = {name: i for i, name in enumerate(names)}
        self.constants: list = []
        self.constant_keys: dict[tuple[str, str], int] = {}
        self.code: list[Instr] = []

    def emit(self, op: str, arg: int | None = None) -> int:
        if has_argument(op) and arg is None:
            raise CompileError(f"opcode {op} requires an argument")
        self.code.append(Instr(op, arg if has_argument(op) else None))
        return len(self.code) - 1

    def patch(self, index: int, target: int) -> None:
        self.code[index] = Instr(self.code[index].op, target)

    def here(self) -> int:
        return len(self.code)

    def constant(self, value: object) -> int:
        # Deduplication is by type *and* value, so 1, 1.0 and true differ.
        key = (type(value).__name__, repr(value))
        if key not in self.constant_keys:
            self.constant_keys[key] = len(self.constants)
            self.constants.append(value)
        return self.constant_keys[key]

    def slot_of(self, identifier: str) -> int:
        if identifier not in self.slots:
            raise CompileError(f"variable {identifier!r} is not declared")
        return self.slots[identifier]

    # -- statements ---------------------------------------------------
    def statement(self, node: object) -> None:
        if isinstance(node, (ast.Let, ast.Assign)):
            self.expression(node.expr)
            self.emit("STORE", self.slot_of(node.identifier))
        elif isinstance(node, ast.Print):
            self.expression(node.expr)
            self.emit("PRINT")
        elif isinstance(node, ast.Block):
            for statement in node.statements:
                self.statement(statement)
        elif isinstance(node, ast.If):
            self.if_statement(node)
        elif isinstance(node, ast.While):
            self.while_statement(node)
        else:  # pragma: no cover - defensive
            raise CompileError(f"unsupported statement node {type(node).__name__}")

    def if_statement(self, node: ast.If) -> None:
        self.expression(node.condition)
        to_else = self.emit("JUMP_IF_FALSE", 0)
        self.statement(node.then_branch)
        if node.else_branch is None:
            self.patch(to_else, self.here())
            return
        to_end = self.emit("JUMP", 0)
        self.patch(to_else, self.here())
        self.statement(node.else_branch)
        self.patch(to_end, self.here())

    def while_statement(self, node: ast.While) -> None:
        start = self.here()
        self.expression(node.condition)
        to_end = self.emit("JUMP_IF_FALSE", 0)
        self.statement(node.body)
        self.emit("JUMP", start)
        self.patch(to_end, self.here())

    # -- expressions --------------------------------------------------
    def expression(self, node: object) -> None:
        if isinstance(node, ast.Literal):
            self.emit("CONST", self.constant(node.value))
        elif isinstance(node, ast.Name):
            self.emit("LOAD", self.slot_of(node.identifier))
        elif isinstance(node, ast.Unary):
            self.expression(node.operand)
            self.emit("NEG" if node.op == "-" else "NOT")
        elif isinstance(node, ast.Binary):
            self.expression(node.left)
            self.expression(node.right)
            self.emit(_BINARY_OPCODES[node.op])
        elif isinstance(node, ast.Logical):
            self.logical(node)
        else:  # pragma: no cover - defensive
            raise CompileError(f"unsupported expression node {type(node).__name__}")

    def logical(self, node: ast.Logical) -> None:
        """Compile ``and`` / ``or`` with jumps, keeping the strict BOOL checks.

        ``JUMP_IF_FALSE`` type checks whatever it pops, so both operands are
        still validated as BOOL exactly when they are evaluated.
        """
        false_jumps: list[int] = []
        end_jumps: list[int] = []
        self.expression(node.left)
        if node.op == "and":
            false_jumps.append(self.emit("JUMP_IF_FALSE", 0))
        else:
            to_right = self.emit("JUMP_IF_FALSE", 0)
            self.emit("CONST", self.constant(True))
            end_jumps.append(self.emit("JUMP", 0))
            self.patch(to_right, self.here())
        self.expression(node.right)
        false_jumps.append(self.emit("JUMP_IF_FALSE", 0))
        self.emit("CONST", self.constant(True))
        end_jumps.append(self.emit("JUMP", 0))
        for index in false_jumps:
            self.patch(index, self.here())
        self.emit("CONST", self.constant(False))
        for index in end_jumps:
            self.patch(index, self.here())


def compile_source(src: str, *, optimize: bool = False) -> Program:
    """Compile *src* into a :class:`Program`, optionally folding constants."""
    tree = parse(src)
    if optimize:
        tree = fold_constants(tree)
    if not isinstance(tree, ast.Module):  # pragma: no cover - defensive
        raise CompileError("parser did not return a module")
    names: list[str] = []
    _collect_declarations(tree, names)
    compiler = _Compiler(names)
    for statement in tree.statements:
        compiler.statement(statement)
    compiler.emit("HALT")
    return Program(compiler.constants, compiler.names, compiler.code)
