"""Bytecode compiler for microvm."""

import dataclasses
from microvm.errors import CompileError
from microvm.opcodes import OPCODES
from microvm.optimizer import fold_constants
from microvm.parser import (
    AssignStmt,
    BinaryOp,
    BlockStmt,
    IfStmt,
    LetStmt,
    Literal,
    PrintStmt,
    ProgramNode,
    UnaryOp,
    Var,
    WhileStmt,
    parse,
)

BINARY_OP_TO_OPCODE: dict[str, str] = {
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
    op: str            # one of OPCODES
    arg: int | None    # None exactly when the opcode takes no argument


@dataclasses.dataclass
class Program:
    constants: list        # the constant pool
    names: list[str]       # variable names, slot order = declaration order
    instructions: list     # list[Instr]


def _collect_declarations(node: object, names: list[str], seen: set[str]) -> None:
    if isinstance(node, ProgramNode):
        for stmt in node.stmts:
            _collect_declarations(stmt, names, seen)
    elif isinstance(node, BlockStmt):
        for stmt in node.stmts:
            _collect_declarations(stmt, names, seen)
    elif isinstance(node, LetStmt):
        if node.name in seen:
            raise CompileError(f"Duplicate declaration of variable '{node.name}'")
        seen.add(node.name)
        names.append(node.name)
    elif isinstance(node, IfStmt):
        for stmt in node.then_block:
            _collect_declarations(stmt, names, seen)
        if isinstance(node.else_branch, list):
            for stmt in node.else_branch:
                _collect_declarations(stmt, names, seen)
        elif isinstance(node.else_branch, IfStmt):
            _collect_declarations(node.else_branch, names, seen)
    elif isinstance(node, WhileStmt):
        for stmt in node.body:
            _collect_declarations(stmt, names, seen)


def _validate_usages(node: object, declared: set[str]) -> None:
    if isinstance(node, ProgramNode):
        for stmt in node.stmts:
            _validate_usages(stmt, declared)
    elif isinstance(node, BlockStmt):
        for stmt in node.stmts:
            _validate_usages(stmt, declared)
    elif isinstance(node, LetStmt):
        _validate_usages(node.expr, declared)
    elif isinstance(node, AssignStmt):
        if node.name not in declared:
            raise CompileError(f"Variable '{node.name}' was never declared")
        _validate_usages(node.expr, declared)
    elif isinstance(node, PrintStmt):
        _validate_usages(node.expr, declared)
    elif isinstance(node, IfStmt):
        _validate_usages(node.cond, declared)
        for stmt in node.then_block:
            _validate_usages(stmt, declared)
        if isinstance(node.else_branch, list):
            for stmt in node.else_branch:
                _validate_usages(stmt, declared)
        elif isinstance(node.else_branch, IfStmt):
            _validate_usages(node.else_branch, declared)
    elif isinstance(node, WhileStmt):
        _validate_usages(node.cond, declared)
        for stmt in node.body:
            _validate_usages(stmt, declared)
    elif isinstance(node, Var):
        if node.name not in declared:
            raise CompileError(f"Variable '{node.name}' was never declared")
    elif isinstance(node, UnaryOp):
        _validate_usages(node.expr, declared)
    elif isinstance(node, BinaryOp):
        _validate_usages(node.left, declared)
        _validate_usages(node.right, declared)


class _Compiler:
    def __init__(self, names: list[str]) -> None:
        self.names: list[str] = names
        self.slot_map: dict[str, int] = {name: i for i, name in enumerate(names)}
        self.constants: list = []
        self.const_map: dict[tuple[type, object], int] = {}
        self.instructions: list[Instr] = []

    def add_constant(self, value: object) -> int:
        key = (type(value), value)
        if key in self.const_map:
            return self.const_map[key]
        idx = len(self.constants)
        self.constants.append(value)
        self.const_map[key] = idx
        return idx

    def emit(self, op: str, arg: int | None = None) -> int:
        idx = len(self.instructions)
        self.instructions.append(Instr(op=op, arg=arg))
        return idx

    def patch(self, instr_idx: int, target: int) -> None:
        op = self.instructions[instr_idx].op
        self.instructions[instr_idx] = Instr(op=op, arg=target)

    def compile_expr(self, expr: object) -> None:
        if isinstance(expr, Literal):
            k = self.add_constant(expr.value)
            self.emit("CONST", k)
        elif isinstance(expr, Var):
            self.emit("LOAD", self.slot_map[expr.name])
        elif isinstance(expr, UnaryOp):
            self.compile_expr(expr.expr)
            self.emit("NEG" if expr.op == "-" else "NOT", None)
        elif isinstance(expr, BinaryOp):
            self.compile_binary_op(expr)

    def compile_binary_op(self, expr: BinaryOp) -> None:
        if expr.op == "and":
            self.compile_expr(expr.left)
            jf1 = self.emit("JUMP_IF_FALSE", 0)
            self.compile_expr(expr.right)
            jf2 = self.emit("JUMP_IF_FALSE", 0)
            self.emit("CONST", self.add_constant(True))
            j_end = self.emit("JUMP", 0)
            self.patch(jf1, len(self.instructions))
            self.patch(jf2, len(self.instructions))
            self.emit("CONST", self.add_constant(False))
            self.patch(j_end, len(self.instructions))
        elif expr.op == "or":
            self.compile_expr(expr.left)
            j_chk = self.emit("JUMP_IF_FALSE", 0)
            self.emit("CONST", self.add_constant(True))
            j_end1 = self.emit("JUMP", 0)
            self.patch(j_chk, len(self.instructions))
            self.compile_expr(expr.right)
            j_rf = self.emit("JUMP_IF_FALSE", 0)
            self.emit("CONST", self.add_constant(True))
            j_end2 = self.emit("JUMP", 0)
            self.patch(j_rf, len(self.instructions))
            self.emit("CONST", self.add_constant(False))
            self.patch(j_end1, len(self.instructions))
            self.patch(j_end2, len(self.instructions))
        else:
            self.compile_expr(expr.left)
            self.compile_expr(expr.right)
            self.emit(BINARY_OP_TO_OPCODE[expr.op], None)

    def compile_stmt(self, stmt: object) -> None:
        if isinstance(stmt, LetStmt):
            self.compile_expr(stmt.expr)
            self.emit("STORE", self.slot_map[stmt.name])
        elif isinstance(stmt, AssignStmt):
            self.compile_expr(stmt.expr)
            self.emit("STORE", self.slot_map[stmt.name])
        elif isinstance(stmt, PrintStmt):
            self.compile_expr(stmt.expr)
            self.emit("PRINT", None)
        elif isinstance(stmt, BlockStmt):
            for s in stmt.stmts:
                self.compile_stmt(s)
        elif isinstance(stmt, IfStmt):
            self.compile_if(stmt)
        elif isinstance(stmt, WhileStmt):
            self.compile_while(stmt)

    def compile_if(self, stmt: IfStmt) -> None:
        self.compile_expr(stmt.cond)
        jf = self.emit("JUMP_IF_FALSE", 0)
        for s in stmt.then_block:
            self.compile_stmt(s)
        if stmt.else_branch is not None:
            j_end = self.emit("JUMP", 0)
            self.patch(jf, len(self.instructions))
            if isinstance(stmt.else_branch, list):
                for s in stmt.else_branch:
                    self.compile_stmt(s)
            elif isinstance(stmt.else_branch, IfStmt):
                self.compile_stmt(stmt.else_branch)
            self.patch(j_end, len(self.instructions))
        else:
            self.patch(jf, len(self.instructions))

    def compile_while(self, stmt: WhileStmt) -> None:
        loop_start = len(self.instructions)
        self.compile_expr(stmt.cond)
        j_exit = self.emit("JUMP_IF_FALSE", 0)
        for s in stmt.body:
            self.compile_stmt(s)
        self.emit("JUMP", loop_start)
        self.patch(j_exit, len(self.instructions))


def compile_source(src: str, *, optimize: bool = False) -> Program:
    ast = parse(src)
    if optimize:
        ast = fold_constants(ast)
    names: list[str] = []
    seen: set[str] = set()
    _collect_declarations(ast, names, seen)
    _validate_usages(ast, seen)
    compiler = _Compiler(names)
    if isinstance(ast, ProgramNode):
        for stmt in ast.stmts:
            compiler.compile_stmt(stmt)
    compiler.emit("HALT", None)
    return Program(
        constants=compiler.constants,
        names=compiler.names,
        instructions=compiler.instructions,
    )
