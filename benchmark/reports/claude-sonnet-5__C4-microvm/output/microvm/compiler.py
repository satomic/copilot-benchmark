"""Bytecode compiler: AST -> Program."""

import dataclasses

from .errors import CompileError
from .opcodes import OPCODES
from .optimizer import fold_constants
from .parser import (
    AssignStmt,
    BinOp,
    BoolLit,
    FloatLit,
    IfStmt,
    IntLit,
    LetStmt,
    LogicOp,
    Module,
    Neg,
    NotOp,
    PrintStmt,
    StrLit,
    VarRef,
    WhileStmt,
    parse,
)


@dataclasses.dataclass(frozen=True)
class Instr:
    op: str
    arg: int | None


@dataclasses.dataclass
class Program:
    constants: list
    names: list[str]
    instructions: list


_BINOP_TO_OPCODE: dict[str, str] = {
    "+": "ADD", "-": "SUB", "*": "MUL", "/": "DIV", "%": "MOD",
    "==": "EQ", "!=": "NE", "<": "LT", "<=": "LE", ">": "GT", ">=": "GE",
}


def _collect_names(stmts: list, names: list[str], slots: dict[str, int]) -> None:
    for stmt in stmts:
        if isinstance(stmt, LetStmt):
            if stmt.name in slots:
                raise CompileError(f"variable {stmt.name!r} already declared")
            slots[stmt.name] = len(names)
            names.append(stmt.name)
        elif isinstance(stmt, Module):
            _collect_names(stmt.body, names, slots)
        elif isinstance(stmt, IfStmt):
            _collect_names(stmt.then_body, names, slots)
            if stmt.else_body is not None:
                _collect_names(stmt.else_body, names, slots)
        elif isinstance(stmt, WhileStmt):
            _collect_names(stmt.body, names, slots)


def _check_names_stmts(stmts: list, slots: dict[str, int]) -> None:
    for stmt in stmts:
        if isinstance(stmt, LetStmt):
            _check_names_expr(stmt.expr, slots)
        elif isinstance(stmt, AssignStmt):
            if stmt.name not in slots:
                raise CompileError(f"assignment to undeclared variable {stmt.name!r}")
            _check_names_expr(stmt.expr, slots)
        elif isinstance(stmt, PrintStmt):
            _check_names_expr(stmt.expr, slots)
        elif isinstance(stmt, Module):
            _check_names_stmts(stmt.body, slots)
        elif isinstance(stmt, IfStmt):
            _check_names_expr(stmt.cond, slots)
            _check_names_stmts(stmt.then_body, slots)
            if stmt.else_body is not None:
                _check_names_stmts(stmt.else_body, slots)
        elif isinstance(stmt, WhileStmt):
            _check_names_expr(stmt.cond, slots)
            _check_names_stmts(stmt.body, slots)


def _check_names_expr(node: object, slots: dict[str, int]) -> None:
    if isinstance(node, VarRef):
        if node.name not in slots:
            raise CompileError(f"use of undeclared variable {node.name!r}")
    elif isinstance(node, (Neg, NotOp)):
        _check_names_expr(node.expr, slots)
    elif isinstance(node, (BinOp, LogicOp)):
        _check_names_expr(node.left, slots)
        _check_names_expr(node.right, slots)


class _CodeGen:
    def __init__(self, slots: dict[str, int]) -> None:
        self.slots = slots
        self.instructions: list[Instr] = []
        self.const_index: dict[tuple, int] = {}
        self.constants: list = []

    def emit(self, op: str, arg: int | None = None) -> int:
        self.instructions.append(Instr(op, arg))
        return len(self.instructions) - 1

    def patch(self, index: int, target: int) -> None:
        self.instructions[index] = Instr(self.instructions[index].op, target)

    def here(self) -> int:
        return len(self.instructions)

    def const_id(self, value: object) -> int:
        key = (type(value), value)
        if key in self.const_index:
            return self.const_index[key]
        idx = len(self.constants)
        self.constants.append(value)
        self.const_index[key] = idx
        return idx

    def compile_stmts(self, stmts: list) -> None:
        for stmt in stmts:
            self.compile_stmt(stmt)

    def compile_stmt(self, stmt: object) -> None:
        if isinstance(stmt, Module):
            self.compile_stmts(stmt.body)
        elif isinstance(stmt, LetStmt):
            self.compile_expr(stmt.expr)
            self.emit("STORE", self.slots[stmt.name])
        elif isinstance(stmt, AssignStmt):
            self.compile_expr(stmt.expr)
            self.emit("STORE", self.slots[stmt.name])
        elif isinstance(stmt, PrintStmt):
            self.compile_expr(stmt.expr)
            self.emit("PRINT")
        elif isinstance(stmt, IfStmt):
            self._compile_if(stmt)
        elif isinstance(stmt, WhileStmt):
            self._compile_while(stmt)

    def _compile_if(self, stmt: IfStmt) -> None:
        self.compile_expr(stmt.cond)
        jf = self.emit("JUMP_IF_FALSE")
        self.compile_stmts(stmt.then_body)
        if stmt.else_body is not None:
            jend = self.emit("JUMP")
            self.patch(jf, self.here())
            self.compile_stmts(stmt.else_body)
            self.patch(jend, self.here())
        else:
            self.patch(jf, self.here())

    def _compile_while(self, stmt: WhileStmt) -> None:
        start = self.here()
        self.compile_expr(stmt.cond)
        jf = self.emit("JUMP_IF_FALSE")
        self.compile_stmts(stmt.body)
        self.emit("JUMP", start)
        self.patch(jf, self.here())

    def compile_expr(self, node: object) -> None:
        if isinstance(node, IntLit):
            self.emit("CONST", self.const_id(node.value))
        elif isinstance(node, FloatLit):
            self.emit("CONST", self.const_id(node.value))
        elif isinstance(node, StrLit):
            self.emit("CONST", self.const_id(node.value))
        elif isinstance(node, BoolLit):
            self.emit("CONST", self.const_id(node.value))
        elif isinstance(node, VarRef):
            self.emit("LOAD", self.slots[node.name])
        elif isinstance(node, Neg):
            self.compile_expr(node.expr)
            self.emit("NEG")
        elif isinstance(node, NotOp):
            self.compile_expr(node.expr)
            self.emit("NOT")
        elif isinstance(node, BinOp):
            self.compile_expr(node.left)
            self.compile_expr(node.right)
            self.emit(_BINOP_TO_OPCODE[node.op])
        elif isinstance(node, LogicOp):
            self._compile_logic(node)

    def _compile_logic(self, node: LogicOp) -> None:
        self.compile_expr(node.left)
        jf = self.emit("JUMP_IF_FALSE")
        if node.op == "and":
            self.compile_expr(node.right)
            self.emit("NOT")
            self.emit("NOT")
            jend = self.emit("JUMP")
            self.patch(jf, self.here())
            self.emit("CONST", self.const_id(False))
            self.patch(jend, self.here())
        else:
            self.emit("CONST", self.const_id(True))
            jend = self.emit("JUMP")
            self.patch(jf, self.here())
            self.compile_expr(node.right)
            self.emit("NOT")
            self.emit("NOT")
            self.patch(jend, self.here())


def compile_source(src: str, *, optimize: bool = False) -> Program:
    module = parse(src)
    names: list[str] = []
    slots: dict[str, int] = {}
    _collect_names(module.body, names, slots)
    _check_names_stmts(module.body, slots)
    if optimize:
        module = fold_constants(module)
    gen = _CodeGen(slots)
    gen.compile_stmts(module.body)
    gen.emit("HALT")
    assert all(op in OPCODES for op in (i.op for i in gen.instructions))
    return Program(gen.constants, names, gen.instructions)
