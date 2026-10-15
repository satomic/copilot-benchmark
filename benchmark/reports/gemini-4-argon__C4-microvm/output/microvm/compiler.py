from __future__ import annotations

import dataclasses
import math
from microvm.errors import CompileError
from microvm.optimizer import fold_constants
from microvm.parser import (
    AssignStmt,
    BinOp,
    BlockStmt,
    Expr,
    IfStmt,
    LetStmt,
    Literal,
    LogicOp,
    PrintStmt,
    ProgramAST,
    Stmt,
    UnaryOp,
    Var,
    WhileStmt,
    parse,
)


@dataclasses.dataclass(frozen=True)
class Instr:
    op: str            # one of OPCODES
    arg: int | None    # None exactly when the opcode takes no argument


@dataclasses.dataclass
class Program:
    constants: list        # the constant pool
    names: list[str]       # variable names, slot order = declaration order
    instructions: list     # list[Instr]


BINOP_OPCODES: dict[str, str] = {
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


def _const_key(val: object) -> tuple[type, object]:
    if type(val) is float:
        if math.isnan(val):
            return (float, "nan")
        if val == 0.0:
            return (float, math.copysign(1.0, val), 0.0)
    return (type(val), val)


class _Compiler:
    def __init__(self) -> None:
        self.constants: list[object] = []
        self._const_map: dict[tuple[type, object], int] = {}
        self.names: list[str] = []
        self._name_map: dict[str, int] = {}
        self.instructions: list[Instr] = []

    def add_const(self, val: object) -> int:
        key = _const_key(val)
        if key in self._const_map:
            return self._const_map[key]
        idx = len(self.constants)
        self.constants.append(val)
        self._const_map[key] = idx
        return idx

    def emit(self, op: str, arg: int | None = None) -> int:
        idx = len(self.instructions)
        self.instructions.append(Instr(op, arg))
        return idx

    def patch(self, idx: int, target: int) -> None:
        old = self.instructions[idx]
        self.instructions[idx] = Instr(old.op, target)

    def collect_decls(self, stmts: list[Stmt]) -> None:
        for stmt in stmts:
            if isinstance(stmt, LetStmt):
                if stmt.name in self._name_map:
                    raise CompileError(f"Duplicate declaration of variable {stmt.name!r}")
                slot = len(self.names)
                self.names.append(stmt.name)
                self._name_map[stmt.name] = slot
            elif isinstance(stmt, BlockStmt):
                self.collect_decls(stmt.stmts)
            elif isinstance(stmt, IfStmt):
                self.collect_decls(stmt.then_block.stmts)
                if isinstance(stmt.else_branch, BlockStmt):
                    self.collect_decls(stmt.else_branch.stmts)
                elif isinstance(stmt.else_branch, IfStmt):
                    self.collect_decls([stmt.else_branch])
            elif isinstance(stmt, WhileStmt):
                self.collect_decls(stmt.body.stmts)

    def resolve_var(self, name: str) -> int:
        if name not in self._name_map:
            raise CompileError(f"Undeclared variable {name!r}")
        return self._name_map[name]

    def compile_program(self, ast: ProgramAST, *, optimize: bool = False) -> Program:
        self.collect_decls(ast.stmts)
        self.check_refs_stmts(ast.stmts)
        if optimize:
            folded = fold_constants(ast)
            assert isinstance(folded, ProgramAST)
            ast = folded
        for stmt in ast.stmts:
            self.compile_stmt(stmt)
        self.emit("HALT")
        return Program(self.constants, self.names, self.instructions)

    def check_refs_stmts(self, stmts: list[Stmt]) -> None:
        for stmt in stmts:
            if isinstance(stmt, (LetStmt, AssignStmt)):
                self.resolve_var(stmt.name)
                self.check_refs_expr(stmt.expr)
            elif isinstance(stmt, PrintStmt):
                self.check_refs_expr(stmt.expr)
            elif isinstance(stmt, BlockStmt):
                self.check_refs_stmts(stmt.stmts)
            elif isinstance(stmt, IfStmt):
                self.check_refs_expr(stmt.cond)
                self.check_refs_stmts(stmt.then_block.stmts)
                if isinstance(stmt.else_branch, BlockStmt):
                    self.check_refs_stmts(stmt.else_branch.stmts)
                elif isinstance(stmt.else_branch, IfStmt):
                    self.check_refs_stmts([stmt.else_branch])
            elif isinstance(stmt, WhileStmt):
                self.check_refs_expr(stmt.cond)
                self.check_refs_stmts(stmt.body.stmts)

    def check_refs_expr(self, expr: Expr) -> None:
        if isinstance(expr, Var):
            self.resolve_var(expr.name)
        elif isinstance(expr, UnaryOp):
            self.check_refs_expr(expr.operand)
        elif isinstance(expr, (BinOp, LogicOp)):
            self.check_refs_expr(expr.left)
            self.check_refs_expr(expr.right)

    def compile_stmt(self, stmt: Stmt) -> None:
        if isinstance(stmt, (LetStmt, AssignStmt)):
            slot = self.resolve_var(stmt.name)
            self.compile_expr(stmt.expr)
            self.emit("STORE", slot)
        elif isinstance(stmt, PrintStmt):
            self.compile_expr(stmt.expr)
            self.emit("PRINT")
        elif isinstance(stmt, BlockStmt):
            for s in stmt.stmts:
                self.compile_stmt(s)
        elif isinstance(stmt, IfStmt):
            self._compile_if(stmt)
        elif isinstance(stmt, WhileStmt):
            self._compile_while(stmt)

    def _compile_if(self, stmt: IfStmt) -> None:
        self.compile_expr(stmt.cond)
        jfalse = self.emit("JUMP_IF_FALSE", 0)
        self.compile_stmt(stmt.then_block)
        if stmt.else_branch is None:
            self.patch(jfalse, len(self.instructions))
        else:
            jend = self.emit("JUMP", 0)
            self.patch(jfalse, len(self.instructions))
            self.compile_stmt(stmt.else_branch)
            self.patch(jend, len(self.instructions))

    def _compile_while(self, stmt: WhileStmt) -> None:
        loop_start = len(self.instructions)
        self.compile_expr(stmt.cond)
        jfalse = self.emit("JUMP_IF_FALSE", 0)
        self.compile_stmt(stmt.body)
        self.emit("JUMP", loop_start)
        self.patch(jfalse, len(self.instructions))

    def compile_expr(self, expr: Expr) -> None:
        if isinstance(expr, Literal):
            self.emit("CONST", self.add_const(expr.value))
        elif isinstance(expr, Var):
            self.emit("LOAD", self.resolve_var(expr.name))
        elif isinstance(expr, UnaryOp):
            self.compile_expr(expr.operand)
            self.emit("NEG" if expr.op == "-" else "NOT")
        elif isinstance(expr, BinOp):
            self.compile_expr(expr.left)
            self.compile_expr(expr.right)
            self.emit(BINOP_OPCODES[expr.op])
        elif isinstance(expr, LogicOp):
            self._compile_logic(expr)

    def _compile_logic(self, expr: LogicOp) -> None:
        if expr.op == "and":
            self.compile_expr(expr.left)
            jfalse1 = self.emit("JUMP_IF_FALSE", 0)
            self.compile_expr(expr.right)
            jfalse2 = self.emit("JUMP_IF_FALSE", 0)
            self.emit("CONST", self.add_const(True))
            jend = self.emit("JUMP", 0)
            false_pos = self.emit("CONST", self.add_const(False))
            self.patch(jfalse1, false_pos)
            self.patch(jfalse2, false_pos)
            self.patch(jend, len(self.instructions))
        else:
            self.compile_expr(expr.left)
            jfalse1 = self.emit("JUMP_IF_FALSE", 0)
            self.emit("CONST", self.add_const(True))
            jend1 = self.emit("JUMP", 0)
            right_pos = len(self.instructions)
            self.patch(jfalse1, right_pos)
            self.compile_expr(expr.right)
            jfalse2 = self.emit("JUMP_IF_FALSE", 0)
            self.emit("CONST", self.add_const(True))
            jend2 = self.emit("JUMP", 0)
            false_pos = self.emit("CONST", self.add_const(False))
            self.patch(jfalse2, false_pos)
            end_pos = len(self.instructions)
            self.patch(jend1, end_pos)
            self.patch(jend2, end_pos)


def compile_source(src: str, *, optimize: bool = False) -> Program:
    ast = parse(src)
    assert isinstance(ast, ProgramAST)
    return _Compiler().compile_program(ast, optimize=optimize)
