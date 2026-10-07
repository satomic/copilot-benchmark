from collections.abc import Iterator
from dataclasses import dataclass, field
import struct

from .errors import CompileError
from .optimizer import fold_constants
from .parser import Node, Value, parse


@dataclass(frozen=True)
class Instr:
    op: str
    arg: int | None = None


@dataclass
class Program:
    constants: list[Value] = field(default_factory=list)
    names: list[str] = field(default_factory=list)
    instructions: list[Instr] = field(default_factory=list)


_BINARY = {
    "+": "ADD", "-": "SUB", "*": "MUL", "/": "DIV", "%": "MOD",
    "==": "EQ", "!=": "NE", "<": "LT", "<=": "LE", ">": "GT", ">=": "GE",
}


def _walk(node: Node) -> Iterator[Node]:
    yield node
    for child in node.children:
        yield from _walk(child)


class _Compiler:
    def __init__(self, root: Node) -> None:
        self.program = Program()
        self.slots: dict[str, int] = {}
        self.pool: dict[tuple[type, Value | bytes], int] = {}
        # Declarations are global, including forward and unreachable declarations.
        for node in _walk(root):
            if node.kind == "let":
                assert isinstance(node.value, str)
                if node.value in self.slots:
                    raise CompileError(f"Duplicate declaration: {node.value}")
                self.slots[node.value] = len(self.program.names)
                self.program.names.append(node.value)
        for node in _walk(root):
            if node.kind in ("name", "assign") and node.value not in self.slots:
                raise CompileError(f"Undeclared variable: {node.value}")

    def emit(self, op: str, arg: int | None = None) -> int:
        index = len(self.program.instructions)
        self.program.instructions.append(Instr(op, arg))
        return index

    def patch(self, index: int) -> None:
        old = self.program.instructions[index]
        self.program.instructions[index] = Instr(old.op, len(self.program.instructions))

    def literal(self, value: Value) -> None:
        # Signed floating zero has distinct printed output, despite numeric equality.
        key = (type(value), struct.pack(">d", value) if type(value) is float else value)
        if key not in self.pool:
            self.pool[key] = len(self.program.constants)
            self.program.constants.append(value)
        self.emit("CONST", self.pool[key])

    def logic(self, node: Node) -> None:
        left, right = node.children
        self.generate(left)
        branch = self.emit("JUMP_IF_FALSE", 0)
        if node.value == "or":
            self.literal(True)
            end = self.emit("JUMP", 0)
            self.patch(branch)
            self.generate(right)
            self.emit("NOT")
            self.emit("NOT")
            self.patch(end)
        else:
            self.generate(right)
            # Double NOT validates the evaluated RHS without changing its value.
            self.emit("NOT")
            self.emit("NOT")
            end = self.emit("JUMP", 0)
            self.patch(branch)
            self.literal(False)
            self.patch(end)

    def conditional(self, node: Node) -> None:
        self.generate(node.children[0])
        branch = self.emit("JUMP_IF_FALSE", 0)
        self.generate(node.children[1])
        if len(node.children) == 3:
            end = self.emit("JUMP", 0)
            self.patch(branch)
            self.generate(node.children[2])
            self.patch(end)
        else:
            self.patch(branch)

    def loop(self, node: Node) -> None:
        start = len(self.program.instructions)
        self.generate(node.children[0])
        end = self.emit("JUMP_IF_FALSE", 0)
        self.generate(node.children[1])
        self.emit("JUMP", start)
        self.patch(end)

    def generate(self, node: Node) -> None:
        if node.kind == "literal":
            assert node.value is not None
            self.literal(node.value)
        elif node.kind == "name":
            assert isinstance(node.value, str)
            self.emit("LOAD", self.slots[node.value])
        elif node.kind == "block":
            for child in node.children:
                self.generate(child)
        elif node.kind in ("let", "assign"):
            assert isinstance(node.value, str)
            self.generate(node.children[0])
            self.emit("STORE", self.slots[node.value])
        elif node.kind == "print":
            self.generate(node.children[0])
            self.emit("PRINT")
        elif node.kind == "unary":
            self.generate(node.children[0])
            self.emit("NOT" if node.value == "not" else "NEG")
        elif node.kind == "binary":
            if node.value in ("and", "or"):
                self.logic(node)
            else:
                assert isinstance(node.value, str)
                self.generate(node.children[0])
                self.generate(node.children[1])
                self.emit(_BINARY[node.value])
        elif node.kind == "if":
            self.conditional(node)
        elif node.kind == "while":
            self.loop(node)
        else:
            raise CompileError(f"Unknown AST node: {node.kind}")


def compile_source(src: str, *, optimize: bool = False) -> Program:
    root = parse(src)
    assert isinstance(root, Node)
    compiler = _Compiler(root)
    if optimize:
        root = fold_constants(root)
        assert isinstance(root, Node)
    compiler.generate(root)
    compiler.emit("HALT")
    return compiler.program
