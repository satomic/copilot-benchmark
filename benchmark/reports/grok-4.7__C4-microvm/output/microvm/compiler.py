import dataclasses
import struct
from typing import cast

from microvm.optimizer import fold_constants
from microvm.parser import (
    AssignStmt,
    BinaryOp,
    Block,
    BoolLit,
    FloatLit,
    Ident,
    IfStmt,
    IntLit,
    LetStmt,
    PrintStmt,
    ProgramNode,
    StringLit,
    UnaryOp,
    WhileStmt,
    parse,
)
from microvm.errors import CompileError

_LITERALS = (IntLit, FloatLit, StringLit, BoolLit)
_BIN_OPS = {
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
    op: str
    arg: int | None


@dataclasses.dataclass
class Program:
    constants: list[object]
    names: list[str]
    instructions: list[Instr]


def compile_source(src: str, *, optimize: bool = False) -> Program:
    tree = parse(src)
    if optimize:
        tree = fold_constants(tree)
    return _emit_program(tree)


def _emit_program(tree: object) -> Program:
    root = cast(ProgramNode, tree)
    names = _declare(root)
    compiler = _Compiler(names)
    for stmt in root.statements:
        compiler.statement(stmt)
    compiler.emit("HALT")
    return Program(compiler.constants, names, compiler.instructions)


def _declare(node: object) -> list[str]:
    found: list[str] = []
    _walk_decls(node, found, set())
    return found


def _walk_decls(node: object, found: list[str], seen: set[str]) -> None:
    if type(node) is LetStmt:
        let = cast(LetStmt, node)
        if let.name in seen:
            raise CompileError(f"duplicate declaration: {let.name}")
        seen.add(let.name)
        found.append(let.name)
    for child in _children(node):
        _walk_decls(child, found, seen)


def _children(node: object) -> list[object]:
    kind = type(node)
    if kind is ProgramNode:
        return list(cast(ProgramNode, node).statements)
    if kind is Block:
        return list(cast(Block, node).statements)
    if kind is LetStmt:
        return [cast(LetStmt, node).expr]
    if kind is AssignStmt:
        return [cast(AssignStmt, node).expr]
    if kind is PrintStmt:
        return [cast(PrintStmt, node).expr]
    if kind is IfStmt:
        return _if_children(cast(IfStmt, node))
    if kind is WhileStmt:
        stmt = cast(WhileStmt, node)
        return [stmt.cond, stmt.body]
    if kind is BinaryOp:
        expr = cast(BinaryOp, node)
        return [expr.left, expr.right]
    if kind is UnaryOp:
        return [cast(UnaryOp, node).operand]
    return []


def _if_children(stmt: IfStmt) -> list[object]:
    children = [stmt.cond, stmt.then_body]
    if stmt.else_body is not None:
        children.append(stmt.else_body)
    return children


def _pool_key(value: object) -> object:
    # -0.0 and 0.0 compare equal but str() differs; keep both pool entries.
    if type(value) is float:
        return ("float", struct.pack(">d", value))
    return (type(value), value)


class _Compiler:
    def __init__(self, names: list[str]) -> None:
        self.constants: list[object] = []
        self.instructions: list[Instr] = []
        self._keys: dict[object, int] = {}
        self._names = {name: index for index, name in enumerate(names)}

    def emit(self, op: str, arg: int | None = None) -> int:
        self.instructions.append(Instr(op, arg))
        return len(self.instructions) - 1

    def patch(self, index: int, arg: int) -> None:
        self.instructions[index] = Instr(self.instructions[index].op, arg)

    def pool(self, value: object) -> int:
        key = _pool_key(value)
        found = self._keys.get(key)
        if found is not None:
            return found
        index = len(self.constants)
        self.constants.append(value)
        self._keys[key] = index
        return index

    def statement(self, node: object) -> None:
        kind = type(node)
        if kind is Block:
            self._block(cast(Block, node))
            return
        if kind is LetStmt:
            self._let(cast(LetStmt, node))
            return
        if kind is AssignStmt:
            self._assign(cast(AssignStmt, node))
            return
        if kind is PrintStmt:
            self._print(cast(PrintStmt, node))
            return
        if kind is IfStmt:
            self._if(cast(IfStmt, node))
            return
        if kind is WhileStmt:
            self._while(cast(WhileStmt, node))
            return
        raise CompileError("invalid statement")

    def expression(self, node: object) -> None:
        if type(node) in _LITERALS:
            self.emit("CONST", self.pool(_literal_value(node)))
            return
        if type(node) is Ident:
            self._load(cast(Ident, node).name)
            return
        if type(node) is UnaryOp:
            self._unary(cast(UnaryOp, node))
            return
        if type(node) is BinaryOp:
            self._binary(cast(BinaryOp, node))
            return
        raise CompileError("invalid expression")

    def _block(self, node: Block) -> None:
        for stmt in node.statements:
            self.statement(stmt)

    def _let(self, node: LetStmt) -> None:
        self.expression(node.expr)
        self.emit("STORE", self._slot(node.name))

    def _assign(self, node: AssignStmt) -> None:
        self.expression(node.expr)
        self.emit("STORE", self._slot(node.name))

    def _print(self, node: PrintStmt) -> None:
        self.expression(node.expr)
        self.emit("PRINT")

    def _if(self, node: IfStmt) -> None:
        self.expression(node.cond)
        jump_false = self.emit("JUMP_IF_FALSE", 0)
        self.statement(node.then_body)
        if node.else_body is None:
            self.patch(jump_false, len(self.instructions))
            return
        jump_end = self.emit("JUMP", 0)
        self.patch(jump_false, len(self.instructions))
        self.statement(node.else_body)
        self.patch(jump_end, len(self.instructions))

    def _while(self, node: WhileStmt) -> None:
        start = len(self.instructions)
        self.expression(node.cond)
        jump_false = self.emit("JUMP_IF_FALSE", 0)
        self.statement(node.body)
        self.emit("JUMP", start)
        self.patch(jump_false, len(self.instructions))

    def _unary(self, node: UnaryOp) -> None:
        self.expression(node.operand)
        if node.op == "-":
            self.emit("NEG")
            return
        if node.op == "not":
            self.emit("NOT")
            return
        raise CompileError(f"unknown unary operator: {node.op}")

    def _binary(self, node: BinaryOp) -> None:
        if node.op == "and":
            self._and(node)
            return
        if node.op == "or":
            self._or(node)
            return
        self.expression(node.left)
        self.expression(node.right)
        opcode = _BIN_OPS.get(node.op)
        if opcode is None:
            raise CompileError(f"unknown operator: {node.op}")
        self.emit(opcode)

    def _and(self, node: BinaryOp) -> None:
        # NOT/NOT checks the evaluated right operand is BOOL; no check opcode exists.
        self.expression(node.left)
        jump_false = self.emit("JUMP_IF_FALSE", 0)
        self.expression(node.right)
        self.emit("NOT")
        self.emit("NOT")
        jump_end = self.emit("JUMP", 0)
        self.patch(jump_false, len(self.instructions))
        self.emit("CONST", self.pool(False))
        self.patch(jump_end, len(self.instructions))

    def _or(self, node: BinaryOp) -> None:
        self.expression(node.left)
        jump_false = self.emit("JUMP_IF_FALSE", 0)
        self.emit("CONST", self.pool(True))
        jump_end = self.emit("JUMP", 0)
        self.patch(jump_false, len(self.instructions))
        self.expression(node.right)
        self.emit("NOT")
        self.emit("NOT")
        self.patch(jump_end, len(self.instructions))

    def _load(self, name: str) -> None:
        self.emit("LOAD", self._slot(name))

    def _slot(self, name: str) -> int:
        slot = self._names.get(name)
        if slot is None:
            raise CompileError(f"undeclared variable: {name}")
        return slot


def _literal_value(node: object) -> object:
    if type(node) is IntLit:
        return cast(IntLit, node).value
    if type(node) is FloatLit:
        return cast(FloatLit, node).value
    if type(node) is StringLit:
        return cast(StringLit, node).value
    if type(node) is BoolLit:
        return cast(BoolLit, node).value
    raise CompileError("invalid literal")
