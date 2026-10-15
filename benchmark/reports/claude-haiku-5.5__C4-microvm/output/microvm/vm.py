"""Stack virtual machine that executes compiled Programs."""

from __future__ import annotations

import operator
from collections.abc import Callable
from typing import TYPE_CHECKING

from .errors import StepLimitError, VMRuntimeError

if TYPE_CHECKING:
    from .compiler import Instr, Program

_UNSET = object()
_BINARY_SYMBOLS: dict[str, str] = {
    "ADD": "+", "SUB": "-", "MUL": "*", "DIV": "/", "MOD": "%",
    "EQ": "==", "NE": "!=", "LT": "<", "LE": "<=", "GT": ">", "GE": ">=",
}
_UNARY_SYMBOLS: dict[str, str] = {"NEG": "-", "NOT": "not"}
_ARITH_OPS: dict[str, Callable[[object, object], object]] = {
    "+": operator.add, "-": operator.sub, "*": operator.mul,
    "/": operator.truediv, "%": operator.mod,
}
_ORDER_OPS: dict[str, Callable[[object, object], bool]] = {
    "<": operator.lt, "<=": operator.le, ">": operator.gt, ">=": operator.ge,
}
_CONDITIONAL_OPS: frozenset[str] = frozenset({"JUMP", "JUMP_IF_FALSE"})


def _is_bool(value: object) -> bool:
    return type(value) is bool


def _is_num(value: object) -> bool:
    return type(value) in (int, float)


def binary_op(symbol: str, left: object, right: object) -> object:
    """Apply a binary operator under MicroVM rules; shared with the optimizer."""
    if symbol == "==":
        return _equal(left, right)
    if symbol == "!=":
        return not _equal(left, right)
    if symbol in _ORDER_OPS:
        return _order(symbol, left, right)
    return _arithmetic(symbol, left, right)


def unary_op(symbol: str, operand: object) -> object:
    """Apply ``not`` or unary minus under MicroVM rules."""
    if symbol == "not":
        if not _is_bool(operand):
            raise VMRuntimeError("'not' requires a BOOL operand")
        return not operand
    if not _is_num(operand):
        raise VMRuntimeError("unary '-' requires a number")
    return -operand  # type: ignore[operator]


def _equal(left: object, right: object) -> bool:
    if _is_bool(left) or _is_bool(right):
        return _is_bool(left) and _is_bool(right) and left == right
    if _is_num(left) and _is_num(right):
        return left == right  # type: ignore[operator]
    if type(left) is str and type(right) is str:
        return left == right
    return False


def _order(symbol: str, left: object, right: object) -> bool:
    comparable = (_is_num(left) and _is_num(right)) or (
        type(left) is str and type(right) is str
    )
    if not comparable:
        raise VMRuntimeError(f"'{symbol}' requires two numbers or two strings")
    return _ORDER_OPS[symbol](left, right)


def _arithmetic(symbol: str, left: object, right: object) -> object:
    if symbol == "+" and type(left) is str and type(right) is str:
        return left + right
    if not (_is_num(left) and _is_num(right)):
        raise VMRuntimeError(f"'{symbol}' requires numbers")
    if symbol in ("/", "%") and right == 0:
        raise VMRuntimeError("division by zero")
    if symbol == "%" and not (type(left) is int and type(right) is int):
        raise VMRuntimeError("'%' requires INT operands")
    try:
        return _ARITH_OPS[symbol](left, right)
    except OverflowError as exc:
        raise VMRuntimeError("numeric overflow") from exc


def render(value: object) -> str:
    """Render a value for ``print``."""
    if _is_bool(value):
        return "true" if value else "false"
    if type(value) is str:
        return value
    try:
        return str(value)
    except ValueError as exc:
        raise VMRuntimeError("integer too large to print") from exc


class _Machine:
    """Mutable execution state for one run of a Program."""

    def __init__(self, program: Program) -> None:
        self.program = program
        self.stack: list[object] = []
        self.slots: list[object] = [_UNSET] * len(program.names)
        self.output: list[str] = []
        self.ip: int = 0

    def run(self, step_limit: int) -> list[str]:
        steps = 0
        while True:
            instr = self.fetch()
            steps += 1
            if steps > step_limit:
                raise StepLimitError(f"step limit of {step_limit} exceeded")
            self.ip += 1
            if instr.op == "HALT":
                return self.output
            self.dispatch(instr)

    def fetch(self) -> Instr:
        instructions = self.program.instructions
        if not 0 <= self.ip < len(instructions):
            raise VMRuntimeError(f"instruction pointer {self.ip} is out of range")
        return instructions[self.ip]

    def pop(self) -> object:
        if not self.stack:
            raise VMRuntimeError("operand stack underflow")
        return self.stack.pop()

    def dispatch(self, instr: Instr) -> None:
        op = instr.op
        if op in _BINARY_SYMBOLS:
            right = self.pop()
            left = self.pop()
            self.stack.append(binary_op(_BINARY_SYMBOLS[op], left, right))
        elif op in _UNARY_SYMBOLS:
            self.stack.append(unary_op(_UNARY_SYMBOLS[op], self.pop()))
        elif op in ("CONST", "LOAD", "STORE") or op in _CONDITIONAL_OPS:
            if instr.arg is None:
                raise VMRuntimeError(f"{op} is missing its argument")
            self.dispatch_arg(op, instr.arg)
        else:
            self.dispatch_plain(op)

    def dispatch_arg(self, op: str, arg: int) -> None:
        if op == "CONST":
            self.stack.append(self.constant(arg))
        elif op == "LOAD":
            self.stack.append(self.read(arg))
        elif op == "STORE":
            self.write(arg, self.pop())
        elif op == "JUMP":
            self.ip = arg
        else:
            cond = self.pop()
            if not _is_bool(cond):
                raise VMRuntimeError("condition must be a BOOL")
            if cond is False:
                self.ip = arg

    def dispatch_plain(self, op: str) -> None:
        if op == "PRINT":
            self.output.append(render(self.pop()))
        elif op == "POP":
            self.pop()
        else:
            raise VMRuntimeError(f"unknown opcode {op}")

    def constant(self, index: int) -> object:
        if not 0 <= index < len(self.program.constants):
            raise VMRuntimeError(f"constant index {index} out of range")
        return self.program.constants[index]

    def slot(self, index: int) -> int:
        if not 0 <= index < len(self.slots):
            raise VMRuntimeError(f"variable slot {index} out of range")
        return index

    def read(self, index: int) -> object:
        slot = self.slot(index)
        value = self.slots[slot]
        if value is _UNSET:
            name = self.program.names[slot]
            raise VMRuntimeError(f"variable '{name}' read before assignment")
        return value

    def write(self, index: int, value: object) -> None:
        self.slots[self.slot(index)] = value


def execute(program: Program, *, step_limit: int = 100_000) -> list[str]:
    """Run ``program`` and return its printed lines.

    Raises StepLimitError once more than ``step_limit`` instructions have run.
    """
    if type(step_limit) is not int or step_limit < 1:
        raise ValueError("step_limit must be a positive int")
    return _Machine(program).run(step_limit)
