from dataclasses import dataclass

from .errors import CompileError
from .opcodes import OPCODES
from .parser import Assign, Binary, Block, If, Let, Literal, Print, Unary, Variable, While, parse


@dataclass(frozen=True)
class Instr:
    op: str
    arg: int | None


@dataclass
class Program:
    constants: list
    names: list[str]
    instructions: list


_BINARY_OPS = {
    "+": "ADD", "-": "SUB", "*": "MUL", "/": "DIV", "%": "MOD",
    "==": "EQ", "!=": "NE", "<": "LT", "<=": "LE", ">": "GT", ">=": "GE",
}


def _walk_declarations(node: object, names: list[str], seen: set[str]) -> None:
    if isinstance(node, Let):
        if node.name in seen:
            raise CompileError(f"duplicate declaration: {node.name}")
        seen.add(node.name)
        names.append(node.name)
    elif isinstance(node, Block):
        for statement in node.statements:
            _walk_declarations(statement, names, seen)
    elif isinstance(node, If):
        _walk_declarations(node.then_branch, names, seen)
        if node.else_branch is not None:
            _walk_declarations(node.else_branch, names, seen)
    elif isinstance(node, While):
        _walk_declarations(node.body, names, seen)


def _validate_names(node: object, declared: set[str]) -> None:
    if isinstance(node, Variable) and node.name not in declared:
        raise CompileError(f"undeclared variable: {node.name}")
    if isinstance(node, Assign) and node.name not in declared:
        raise CompileError(f"undeclared variable: {node.name}")
    for child in _children(node):
        _validate_names(child, declared)


def _children(node: object) -> tuple[object, ...]:
    if isinstance(node, (Literal, Variable)):
        return ()
    if isinstance(node, Unary):
        return (node.operand,)
    if isinstance(node, Binary):
        return (node.left, node.right)
    if isinstance(node, (Let, Assign, Print)):
        return (node.value,)
    if isinstance(node, If):
        tail = () if node.else_branch is None else (node.else_branch,)
        return (node.condition, node.then_branch) + tail
    if isinstance(node, While):
        return (node.condition, node.body)
    if isinstance(node, Block):
        return node.statements
    raise CompileError("invalid AST node")


class _Compiler:
    def __init__(self, names: list[str]) -> None:
        self.names = names
        self.slots = {name: index for index, name in enumerate(names)}
        self.constants: list[object] = []
        self.instructions: list[Instr] = []

    def emit(self, op: str, arg: int | None = None) -> int:
        if op not in OPCODES:
            raise CompileError(f"unknown opcode: {op}")
        self.instructions.append(Instr(op, arg))
        return len(self.instructions) - 1

    def patch(self, index: int, target: int) -> None:
        self.instructions[index] = Instr(self.instructions[index].op, target)

    def constant(self, value: object) -> int:
        for index, existing in enumerate(self.constants):
            if type(existing) is type(value) and existing == value:
                return index
        self.constants.append(value)
        return len(self.constants) - 1

    def statement(self, node: object) -> None:
        if isinstance(node, Block):
            for statement in node.statements:
                self.statement(statement)
        elif isinstance(node, (Let, Assign)):
            self.expression(node.value)
            self.emit("STORE", self.slots[node.name])
        elif isinstance(node, Print):
            self.expression(node.value)
            self.emit("PRINT")
        elif isinstance(node, If):
            self.if_statement(node)
        elif isinstance(node, While):
            self.while_statement(node)
        else:
            raise CompileError("invalid statement")

    def if_statement(self, node: If) -> None:
        self.expression(node.condition)
        false_jump = self.emit("JUMP_IF_FALSE", 0)
        self.statement(node.then_branch)
        if node.else_branch is None:
            self.patch(false_jump, len(self.instructions))
            return
        end_jump = self.emit("JUMP", 0)
        self.patch(false_jump, len(self.instructions))
        self.statement(node.else_branch)
        self.patch(end_jump, len(self.instructions))

    def while_statement(self, node: While) -> None:
        start = len(self.instructions)
        self.expression(node.condition)
        end_jump = self.emit("JUMP_IF_FALSE", 0)
        self.statement(node.body)
        self.emit("JUMP", start)
        self.patch(end_jump, len(self.instructions))

    def expression(self, node: object) -> None:
        if isinstance(node, Literal):
            self.emit("CONST", self.constant(node.value))
        elif isinstance(node, Variable):
            self.emit("LOAD", self.slots[node.name])
        elif isinstance(node, Unary):
            self.expression(node.operand)
            self.emit("NEG" if node.op == "-" else "NOT")
        elif isinstance(node, Binary) and node.op in ("and", "or"):
            self.logical(node)
        elif isinstance(node, Binary):
            self.expression(node.left)
            self.expression(node.right)
            self.emit(_BINARY_OPS[node.op])
        else:
            raise CompileError("invalid expression")

    def logical(self, node: Binary) -> None:
        self.expression(node.left)
        left_false = self.emit("JUMP_IF_FALSE", 0)
        if node.op == "or":
            self.emit("CONST", self.constant(True))
            end_left = self.emit("JUMP", 0)
            self.patch(left_false, len(self.instructions))
        self.expression(node.right)
        right_false = self.emit("JUMP_IF_FALSE", 0)
        self.emit("CONST", self.constant(True))
        end_right = self.emit("JUMP", 0)
        false_target = len(self.instructions)
        self.emit("CONST", self.constant(False))
        end = len(self.instructions)
        self.patch(right_false, false_target)
        self.patch(end_right, end)
        if node.op == "and":
            self.patch(left_false, false_target)
        else:
            self.patch(end_left, end)


def compile_source(src: str, *, optimize: bool = False) -> Program:
    root = parse(src)
    if optimize:
        from .optimizer import fold_constants
        root = fold_constants(root)
    names: list[str] = []
    _walk_declarations(root, names, set())
    _validate_names(root, set(names))
    compiler = _Compiler(names)
    compiler.statement(root)
    compiler.emit("HALT")
    return Program(compiler.constants, names, compiler.instructions)
