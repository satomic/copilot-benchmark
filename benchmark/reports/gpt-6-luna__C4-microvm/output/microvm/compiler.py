from dataclasses import dataclass
import struct

from .errors import CompileError
from .opcodes import OPCODES
from .parser import Assign, Binary, Block, If, Let, Literal, Name, Print, Unary, While, parse


@dataclass(frozen=True)
class Instr:
    op: str
    arg: int | None


@dataclass
class Program:
    constants: list
    names: list[str]
    instructions: list[Instr]


def compile_source(src: str, *, optimize: bool = False) -> Program:
    from .optimizer import fold_constants

    tree = parse(src)
    if optimize:
        tree = fold_constants(tree)
    return _Compiler(tree).compile()


class _Compiler:
    def __init__(self, tree: Block):
        self.tree = tree
        self.constants: list[object] = []
        self.constant_keys: dict[tuple[type, object], int] = {}
        self.names: list[str] = []
        self.slots: dict[str, int] = {}
        self.instructions: list[Instr] = []

    def compile(self) -> Program:
        self.collect(self.tree)
        self.statement(self.tree)
        self.emit("HALT")
        return Program(self.constants, self.names, self.instructions)

    def collect(self, node: object) -> None:
        if isinstance(node, Block):
            for stmt in node.statements:
                self.collect(stmt)
        elif isinstance(node, Let):
            if node.name in self.slots:
                raise CompileError(f"variable {node.name!r} declared more than once")
            self.slots[node.name] = len(self.names)
            self.names.append(node.name)
        elif isinstance(node, If):
            self.collect(node.consequent)
            if node.alternative is not None:
                self.collect(node.alternative)
        elif isinstance(node, While):
            self.collect(node.body)

    def statement(self, node: object) -> None:
        if isinstance(node, Block):
            for stmt in node.statements:
                self.statement(stmt)
        elif isinstance(node, Let):
            self.expression(node.value)
            self.emit("STORE", self.slots[node.name])
        elif isinstance(node, Assign):
            self.require_name(node.name)
            self.expression(node.value)
            self.emit("STORE", self.slots[node.name])
        elif isinstance(node, Print):
            self.expression(node.value)
            self.emit("PRINT")
        elif isinstance(node, If):
            self.compile_if(node)
        elif isinstance(node, While):
            start = len(self.instructions)
            self.expression(node.condition)
            branch = self.emit("JUMP_IF_FALSE", 0)
            self.statement(node.body)
            self.emit("JUMP", start)
            self.patch(branch, len(self.instructions))
        else:
            raise CompileError(f"unsupported statement {type(node).__name__}")

    def compile_if(self, node: If) -> None:
        self.expression(node.condition)
        branch = self.emit("JUMP_IF_FALSE", 0)
        self.statement(node.consequent)
        if node.alternative is None:
            self.patch(branch, len(self.instructions))
            return
        end_jump = self.emit("JUMP", 0)
        self.patch(branch, len(self.instructions))
        self.statement(node.alternative)
        self.patch(end_jump, len(self.instructions))

    def expression(self, node: object) -> None:
        if isinstance(node, Literal):
            self.emit("CONST", self.constant(node.value))
        elif isinstance(node, Name):
            self.require_name(node.name)
            self.emit("LOAD", self.slots[node.name])
        elif isinstance(node, Unary):
            self.expression(node.operand)
            self.emit("NEG" if node.op == "-" else "NOT")
        elif isinstance(node, Binary) and node.op in {"and", "or"}:
            self.logical(node)
        elif isinstance(node, Binary):
            self.expression(node.left)
            self.expression(node.right)
            self.emit({"+": "ADD", "-": "SUB", "*": "MUL", "/": "DIV", "%": "MOD",
                       "==": "EQ", "!=": "NE", "<": "LT", "<=": "LE",
                       ">": "GT", ">=": "GE"}[node.op])
        else:
            raise CompileError(f"unsupported expression {type(node).__name__}")

    def logical(self, node: Binary) -> None:
        self.expression(node.left)
        branch = self.emit("JUMP_IF_FALSE", 0)
        if node.op == "and":
            self.expression(node.right)
            self.emit("NOT")
            self.emit("NOT")
            end = self.emit("JUMP", 0)
            self.patch(branch, len(self.instructions))
            self.emit("CONST", self.constant(False))
        else:
            self.emit("CONST", self.constant(True))
            end = self.emit("JUMP", 0)
            self.patch(branch, len(self.instructions))
            self.expression(node.right)
            self.emit("NOT")
            self.emit("NOT")
        self.patch(end, len(self.instructions))

    def constant(self, value: object) -> int:
        identity: object = struct.pack(">d", value) if type(value) is float else value
        key = (type(value), identity)
        if key not in self.constant_keys:
            self.constant_keys[key] = len(self.constants)
            self.constants.append(value)
        return self.constant_keys[key]

    def require_name(self, name: str) -> None:
        if name not in self.slots:
            raise CompileError(f"variable {name!r} is not declared")

    def emit(self, op: str, arg: int | None = None) -> int:
        if op not in OPCODES:
            raise CompileError(f"unknown opcode {op}")
        self.instructions.append(Instr(op, arg))
        return len(self.instructions) - 1

    def patch(self, index: int, target: int) -> None:
        self.instructions[index] = Instr(self.instructions[index].op, target)
