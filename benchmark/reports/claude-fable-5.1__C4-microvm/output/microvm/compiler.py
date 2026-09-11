"""AST to bytecode compiler."""

from __future__ import annotations

import dataclasses

from . import parser as ast
from .errors import CompileError
from .optimizer import fold_constants
from .parser import parse


@dataclasses.dataclass(frozen=True)
class Instr:
    op: str
    arg: int | None


@dataclasses.dataclass
class Program:
    constants: list
    names: list[str]
    instructions: list


_BINARY_OPCODES: dict[str, str] = {
    "+": "ADD", "-": "SUB", "*": "MUL", "/": "DIV", "%": "MOD",
    "==": "EQ", "!=": "NE", "<": "LT", "<=": "LE", ">": "GT", ">=": "GE",
}


def _collect_names(node: object, names: list[str]) -> None:
    """Hoist every ``let`` in the program (blocks do not scope) into ``names``."""
    if isinstance(node, ast.Let):
        if node.name in names:
            raise CompileError(f"variable {node.name!r} declared twice")
        names.append(node.name)
    elif isinstance(node, (ast.Module, ast.Block)):
        for stmt in node.stmts:
            _collect_names(stmt, names)
    elif isinstance(node, ast.If):
        _collect_names(node.then, names)
        if node.orelse is not None:
            _collect_names(node.orelse, names)
    elif isinstance(node, ast.While):
        _collect_names(node.body, names)


class _CodeGen:
    def __init__(self, names: list[str]) -> None:
        self.names = names
        self.slots = {name: index for index, name in enumerate(names)}
        self.constants: list = []
        self.const_index: dict[tuple, int] = {}
        self.code: list[Instr] = []

    # -- emission helpers -----------------------------------------------
    def emit(self, op: str, arg: int | None = None) -> int:
        self.code.append(Instr(op, arg))
        return len(self.code) - 1

    def emit_jump(self, op: str) -> int:
        """Emit a jump with a placeholder target; patch it later with ``patch``."""
        return self.emit(op, 0)

    def patch(self, index: int, target: int | None = None) -> None:
        if target is None:
            target = len(self.code)
        self.code[index] = Instr(self.code[index].op, target)

    def const(self, value: object) -> int:
        # Dedup by type and value; repr keeps 0.0 and -0.0 apart while still merging
        # equal values of the same type.
        key = (type(value), repr(value))
        index = self.const_index.get(key)
        if index is None:
            index = len(self.constants)
            self.constants.append(value)
            self.const_index[key] = index
        return index

    def slot(self, name: str) -> int:
        if name not in self.slots:
            raise CompileError(f"undeclared variable {name!r}")
        return self.slots[name]

    # -- statements -----------------------------------------------------
    def gen_stmt(self, node: object) -> None:
        if isinstance(node, (ast.Module, ast.Block)):
            for stmt in node.stmts:
                self.gen_stmt(stmt)
        elif isinstance(node, (ast.Let, ast.Assign)):
            self.gen_expr(node.expr)
            self.emit("STORE", self.slot(node.name))
        elif isinstance(node, ast.Print):
            self.gen_expr(node.expr)
            self.emit("PRINT")
        elif isinstance(node, ast.If):
            self.gen_if(node)
        elif isinstance(node, ast.While):
            self.gen_while(node)
        else:
            raise CompileError(f"unknown statement node {type(node).__name__}")

    def gen_if(self, node: ast.If) -> None:
        self.gen_expr(node.cond)
        to_else = self.emit_jump("JUMP_IF_FALSE")
        self.gen_stmt(node.then)
        if node.orelse is None:
            self.patch(to_else)
            return
        to_end = self.emit_jump("JUMP")
        self.patch(to_else)
        self.gen_stmt(node.orelse)
        self.patch(to_end)

    def gen_while(self, node: ast.While) -> None:
        top = len(self.code)
        self.gen_expr(node.cond)
        exit_jump = self.emit_jump("JUMP_IF_FALSE")
        self.gen_stmt(node.body)
        self.emit("JUMP", top)
        self.patch(exit_jump)

    # -- expressions ----------------------------------------------------
    def gen_expr(self, node: object) -> None:
        if isinstance(node, ast.Literal):
            self.emit("CONST", self.const(node.value))
        elif isinstance(node, ast.Name):
            self.emit("LOAD", self.slot(node.name))
        elif isinstance(node, ast.Unary):
            self.gen_expr(node.operand)
            self.emit("NEG" if node.op == "-" else "NOT")
        elif isinstance(node, ast.Binary):
            if node.op == "and":
                self.gen_and(node)
            elif node.op == "or":
                self.gen_or(node)
            else:
                self.gen_expr(node.left)
                self.gen_expr(node.right)
                self.emit(_BINARY_OPCODES[node.op])
        else:
            raise CompileError(f"unknown expression node {type(node).__name__}")

    def gen_and(self, node: ast.Binary) -> None:
        # Both operands pass through JUMP_IF_FALSE, which enforces the strict-bool rule.
        self.gen_expr(node.left)
        left_false = self.emit_jump("JUMP_IF_FALSE")
        self.gen_expr(node.right)
        right_false = self.emit_jump("JUMP_IF_FALSE")
        self.emit("CONST", self.const(True))
        to_end = self.emit_jump("JUMP")
        self.patch(left_false)
        self.patch(right_false)
        self.emit("CONST", self.const(False))
        self.patch(to_end)

    def gen_or(self, node: ast.Binary) -> None:
        self.gen_expr(node.left)
        left_false = self.emit_jump("JUMP_IF_FALSE")
        self.emit("CONST", self.const(True))
        left_true_end = self.emit_jump("JUMP")
        self.patch(left_false)
        self.gen_expr(node.right)
        right_false = self.emit_jump("JUMP_IF_FALSE")
        self.emit("CONST", self.const(True))
        right_true_end = self.emit_jump("JUMP")
        self.patch(right_false)
        self.emit("CONST", self.const(False))
        self.patch(left_true_end)
        self.patch(right_true_end)


def compile_ast(node: object) -> Program:
    """Generate a ``Program`` from an already parsed (and optionally folded) AST."""
    names: list[str] = []
    _collect_names(node, names)
    gen = _CodeGen(names)
    gen.gen_stmt(node)
    gen.emit("HALT")
    return Program(gen.constants, names, gen.code)


def compile_source(src: str, *, optimize: bool = False) -> Program:
    tree = parse(src)
    if optimize:
        tree = fold_constants(tree)
    return compile_ast(tree)
