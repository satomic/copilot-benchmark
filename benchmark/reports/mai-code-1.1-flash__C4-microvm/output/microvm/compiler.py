import dataclasses

from .errors import CompileError
from .opcodes import ARG_OPCODE_NAMES, OPCODE_NUMBERS
from .optimizer import fold_constants
from .parser import (
    AssignStmt,
    Binary,
    BlockStmt,
    IfStmt,
    LetStmt,
    Literal,
    Name,
    PrintStmt,
    Unary,
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
    instructions: list[Instr]


def _add_constant(pool: list[object], value: object) -> int:
    for index, current in enumerate(pool):
        if type(current) is type(value) and current == value:
            return index
    pool.append(value)
    return len(pool) - 1


def _emit(builder: list[Instr], op: str, arg: int | None = None) -> int:
    index = len(builder)
    builder.append(Instr(op, arg))
    return index


def _patch(builder: list[Instr], index: int, value: int) -> None:
    builder[index] = Instr(builder[index].op, value)


def _name_slots(program: list[object]) -> dict[str, int]:
    slots: dict[str, int] = {}
    for node in program:
        if isinstance(node, LetStmt):
            if node.name in slots:
                raise CompileError(f"Duplicate declaration: {node.name}")
            slots[node.name] = len(slots)
    return slots


def _compile_expr(node: object, slots: dict[str, int], builder: list[Instr], pool: list[object]) -> None:
    if isinstance(node, Literal):
        _emit(builder, "CONST", _add_constant(pool, node.value))
        return
    if isinstance(node, Name):
        if node.name not in slots:
            raise CompileError(f"Name not declared: {node.name}")
        _emit(builder, "LOAD", slots[node.name])
        return
    if isinstance(node, Unary):
        _compile_expr(node.operand, slots, builder, pool)
        if node.op == "neg":
            _emit(builder, "NEG")
            return
        if node.op == "not":
            _emit(builder, "NOT")
            return
        raise CompileError(f"Unsupported unary op: {node.op}")
    if isinstance(node, Binary):
        if node.op == "and":
            _compile_short_and(node.left, node.right, slots, builder, pool)
            return
        if node.op == "or":
            _compile_short_or(node.left, node.right, slots, builder, pool)
            return
        _compile_expr(node.left, slots, builder, pool)
        _compile_expr(node.right, slots, builder, pool)
        _emit(builder, _map_binary(node.op))
        return
    raise CompileError(f"Unsupported expression node: {type(node).__name__}")


def _compile_short_and(left: object, right: object, slots: dict[str, int], builder: list[Instr], pool: list[object]) -> None:
    _compile_expr(left, slots, builder, pool)
    false_jump = _emit(builder, "JUMP_IF_FALSE", 0)
    _compile_expr(right, slots, builder, pool)
    right_jump = _emit(builder, "JUMP_IF_FALSE", 0)
    _emit(builder, "CONST", _add_constant(pool, True))
    end_jump = _emit(builder, "JUMP", 0)
    false_target = len(builder)
    _patch(builder, false_jump, false_target)
    _patch(builder, right_jump, false_target)
    _emit(builder, "CONST", _add_constant(pool, False))
    _patch(builder, end_jump, len(builder))


def _compile_short_or(left: object, right: object, slots: dict[str, int], builder: list[Instr], pool: list[object]) -> None:
    _compile_expr(left, slots, builder, pool)
    left_jump = _emit(builder, "JUMP_IF_FALSE", 0)
    _emit(builder, "CONST", _add_constant(pool, True))
    left_end = _emit(builder, "JUMP", 0)
    false_target = len(builder)
    _patch(builder, left_jump, false_target)
    _compile_expr(right, slots, builder, pool)
    right_jump = _emit(builder, "JUMP_IF_FALSE", 0)
    _emit(builder, "CONST", _add_constant(pool, True))
    end_jump = _emit(builder, "JUMP", 0)
    _patch(builder, right_jump, len(builder))
    _emit(builder, "CONST", _add_constant(pool, False))
    _patch(builder, left_end, len(builder))
    _patch(builder, end_jump, len(builder))


def _map_binary(op: str) -> str:
    mapping = {
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
    if op not in mapping:
        raise CompileError(f"Unsupported binary op: {op}")
    return mapping[op]


def _compile_stmt(node: object, slots: dict[str, int], builder: list[Instr], pool: list[object]) -> None:
    if isinstance(node, LetStmt):
        if node.name in slots:
            raise CompileError(f"Duplicate declaration: {node.name}")
        slots[node.name] = len(slots)
        _compile_expr(node.value, slots, builder, pool)
        _emit(builder, "STORE", slots[node.name])
        return
    if isinstance(node, AssignStmt):
        if node.name not in slots:
            raise CompileError(f"Name not declared: {node.name}")
        _compile_expr(node.value, slots, builder, pool)
        _emit(builder, "STORE", slots[node.name])
        return
    if isinstance(node, PrintStmt):
        _compile_expr(node.value, slots, builder, pool)
        _emit(builder, "PRINT")
        return
    if isinstance(node, BlockStmt):
        for item in node.statements:
            _compile_stmt(item, slots, builder, pool)
        return
    if isinstance(node, IfStmt):
        _compile_expr(node.condition, slots, builder, pool)
        if_false = _emit(builder, "JUMP_IF_FALSE", 0)
        _compile_stmt(node.then_branch, slots, builder, pool)
        if node.else_branch is not None:
            end_jump = _emit(builder, "JUMP", 0)
            _patch(builder, if_false, len(builder))
            _compile_stmt(node.else_branch, slots, builder, pool)
            _patch(builder, end_jump, len(builder))
            return
        _patch(builder, if_false, len(builder))
        return
    if isinstance(node, WhileStmt):
        loop_start = len(builder)
        _compile_expr(node.condition, slots, builder, pool)
        exit_jump = _emit(builder, "JUMP_IF_FALSE", 0)
        _compile_stmt(node.body, slots, builder, pool)
        _emit(builder, "JUMP", loop_start)
        _patch(builder, exit_jump, len(builder))
        return
    raise CompileError(f"Unsupported statement: {type(node).__name__}")


def compile_source(src: str, *, optimize: bool = False) -> Program:
    tree = parse(src)
    if optimize:
        tree = fold_constants(tree)
    slots: dict[str, int] = {}
    pool: list[object] = []
    builder: list[Instr] = []
    for statement in tree:
        _compile_stmt(statement, slots, builder, pool)
    _emit(builder, "HALT")
    return Program(pool, list(slots), builder)
