from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass

from .errors import CompileError
from .optimizer import fold_constants
from .parser import _Node, parse
from .vm import _BINARY_OPS, _Value


@dataclass(frozen=True)
class Instr:
    op: str
    arg: int | None = None


@dataclass
class Program:
    constants: list[_Value]
    names: list[str]
    instructions: list[Instr]


def _walk(node: _Node) -> Iterator[_Node]:
    yield node
    for child in node.children:
        yield from _walk(child)


def _symbols(root: _Node) -> dict[str, int]:
    symbols: dict[str, int] = {}
    for node in _walk(root):
        if node.kind == "let" and isinstance(node.value, str):
            if node.value in symbols:
                raise CompileError(f"Duplicate declaration of {node.value!r}")
            symbols[node.value] = len(symbols)
    # All declarations are global, including those later in source or unreachable.
    for node in _walk(root):
        if node.kind in ("variable", "assign") and node.value not in symbols:
            raise CompileError(f"Undeclared variable {node.value!r}")
    return symbols


class _Compiler:
    def __init__(self, symbols: dict[str, int]) -> None:
        self.symbols = symbols
        self.program = Program([], list(symbols), [])
        self.pool: dict[tuple[type, _Value], int] = {}

    def _emit(self, op: str, arg: int | None = None) -> int:
        index = len(self.program.instructions)
        self.program.instructions.append(Instr(op, arg))
        return index

    def _patch(self, index: int) -> None:
        instr = self.program.instructions[index]
        self.program.instructions[index] = Instr(instr.op, len(self.program.instructions))

    def _constant(self, value: _Value) -> None:
        key = (type(value), value)
        if key not in self.pool:
            self.pool[key] = len(self.program.constants)
            self.program.constants.append(value)
        self._emit("CONST", self.pool[key])

    def _expression(self, node: _Node) -> None:
        if node.kind == "literal" and node.value is not None:
            self._constant(node.value)
        elif node.kind == "variable" and isinstance(node.value, str):
            self._emit("LOAD", self.symbols[node.value])
        elif node.kind == "unary":
            self._expression(node.children[0])
            self._emit("NOT" if node.value == "not" else "NEG")
        elif node.kind == "binary":
            if node.value in ("and", "or"):
                self._logical(node)
            elif isinstance(node.value, str):
                self._expression(node.children[0])
                self._expression(node.children[1])
                self._emit(_BINARY_OPS[node.value])
        else:
            raise CompileError(f"Invalid expression node {node.kind!r}")

    def _logical(self, node: _Node) -> None:
        self._expression(node.children[0])
        branch = self._emit("JUMP_IF_FALSE", 0)
        if node.value == "or":
            self._constant(True)
            end = self._emit("JUMP", 0)
            self._patch(branch)
            self._expression(node.children[1])
            self._emit("NOT")
            self._emit("NOT")
        else:
            self._expression(node.children[1])
            # Two NOTs validate the evaluated RHS without changing its value.
            self._emit("NOT")
            self._emit("NOT")
            end = self._emit("JUMP", 0)
            self._patch(branch)
            self._constant(False)
        self._patch(end)

    def _conditional(self, node: _Node) -> None:
        start = len(self.program.instructions)
        self._expression(node.children[0])
        branch = self._emit("JUMP_IF_FALSE", 0)
        self._statement(node.children[1])
        if node.kind == "while":
            self._emit("JUMP", start)
            self._patch(branch)
        elif len(node.children) == 3:
            end = self._emit("JUMP", 0)
            self._patch(branch)
            self._statement(node.children[2])
            self._patch(end)
        else:
            self._patch(branch)

    def _statement(self, node: _Node) -> None:
        if node.kind == "block":
            for child in node.children:
                self._statement(child)
        elif node.kind in ("let", "assign") and isinstance(node.value, str):
            self._expression(node.children[0])
            self._emit("STORE", self.symbols[node.value])
        elif node.kind == "print":
            self._expression(node.children[0])
            self._emit("PRINT")
        elif node.kind in ("if", "while"):
            self._conditional(node)
        else:
            raise CompileError(f"Invalid statement node {node.kind!r}")


def compile_source(src: str, *, optimize: bool = False) -> Program:
    root = parse(src)
    if not isinstance(root, _Node):
        raise CompileError("Invalid AST")
    compiler = _Compiler(_symbols(root))
    if optimize:
        folded = fold_constants(root)
        if not isinstance(folded, _Node):
            raise CompileError("Invalid optimized AST")
        root = folded
    compiler._statement(root)
    compiler._emit("HALT")
    return compiler.program
