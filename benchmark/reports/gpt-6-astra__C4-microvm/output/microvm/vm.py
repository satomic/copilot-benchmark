from __future__ import annotations

import operator
from typing import TYPE_CHECKING

from .errors import StepLimitError, VMRuntimeError
from .opcodes import _ARG_OPS

if TYPE_CHECKING:
    from .compiler import Program


_Value = int | float | str | bool
_BINARY_OPS = {
    "+": "ADD", "-": "SUB", "*": "MUL", "/": "DIV", "%": "MOD",
    "==": "EQ", "!=": "NE", "<": "LT", "<=": "LE", ">": "GT", ">=": "GE",
}
_ARITHMETIC = {
    "ADD": operator.add, "SUB": operator.sub, "MUL": operator.mul,
    "DIV": operator.truediv, "MOD": operator.mod,
}
_ORDER = {"LT": operator.lt, "LE": operator.le, "GT": operator.gt, "GE": operator.ge}
_UNSET = object()


def _number(value: object) -> bool:
    return type(value) in (int, float)


def _binary(op: str, left: _Value, right: _Value) -> _Value:
    numeric = _number(left) and _number(right)
    strings = type(left) is str and type(right) is str
    if op in ("EQ", "NE"):
        equal = (numeric or type(left) is type(right)) and left == right
        return equal if op == "EQ" else not equal
    if op in _ORDER:
        if not (numeric or strings):
            raise VMRuntimeError(f"{op} requires two numbers or two strings")
        return _ORDER[op](left, right)
    if op == "ADD" and strings:
        return operator.add(left, right)
    if op not in _ARITHMETIC:
        raise VMRuntimeError(f"Unknown binary operation {op!r}")
    if not numeric:
        raise VMRuntimeError(f"{op} requires numbers (not BOOL)")
    if op == "MOD" and (type(left) is not int or type(right) is not int):
        raise VMRuntimeError("MOD requires two INTs")
    if op in ("DIV", "MOD") and right == 0:
        raise VMRuntimeError("Division or modulo by zero")
    try:
        return _ARITHMETIC[op](left, right)
    except (ArithmeticError, ValueError) as error:
        raise VMRuntimeError(f"{op} failed: {error}") from error


def _unary(op: str, value: _Value) -> _Value:
    if op == "NOT":
        if type(value) is not bool:
            raise VMRuntimeError("NOT requires BOOL")
        return not value
    if op == "NEG":
        if not _number(value):
            raise VMRuntimeError("NEG requires a number (not BOOL)")
        return operator.neg(value)
    raise VMRuntimeError(f"Unknown unary operation {op!r}")


def _render(value: _Value) -> str:
    if type(value) is bool:
        return "true" if value else "false"
    return str(value)


def _index(arg: int | None, length: int, op: str) -> int:
    if type(arg) is not int or not 0 <= arg < length:
        raise VMRuntimeError(f"Invalid {op} argument: {arg!r}")
    return arg


def _pop(stack: list[_Value]) -> _Value:
    if not stack:
        raise VMRuntimeError("Stack underflow")
    return stack.pop()


class _Machine:
    def __init__(self, program: Program) -> None:
        self.program = program
        self.slots: list[object] = [_UNSET] * len(program.names)
        self.stack: list[_Value] = []
        self.output: list[str] = []
        self.ip = 0

    def _load(self, arg: int | None) -> None:
        slot = _index(arg, len(self.slots), "LOAD")
        value = self.slots[slot]
        if value is _UNSET:
            raise VMRuntimeError(f"Variable {self.program.names[slot]!r} is unassigned")
        if not isinstance(value, (int, float, str)):
            raise VMRuntimeError("Invalid stored value")
        self.stack.append(value)

    def _step(self) -> bool:
        _index(self.ip, len(self.program.instructions), "instruction pointer")
        instr = self.program.instructions[self.ip]
        op, arg = instr.op, instr.arg
        self.ip += 1
        if op not in _ARG_OPS and arg is not None:
            raise VMRuntimeError(f"{op} does not take an argument")
        if op == "HALT":
            return True
        if op == "CONST":
            value = self.program.constants[_index(arg, len(self.program.constants), op)]
            if type(value) not in (int, float, str, bool):
                raise VMRuntimeError("Invalid constant type")
            self.stack.append(value)
        elif op == "LOAD":
            self._load(arg)
        elif op == "STORE":
            self.slots[_index(arg, len(self.slots), op)] = _pop(self.stack)
        elif op in _BINARY_OPS.values():
            right, left = _pop(self.stack), _pop(self.stack)
            self.stack.append(_binary(op, left, right))
        elif op in ("NEG", "NOT"):
            self.stack.append(_unary(op, _pop(self.stack)))
        elif op in ("JUMP", "JUMP_IF_FALSE"):
            target = _index(arg, len(self.program.instructions), op)
            if op == "JUMP":
                self.ip = target
            else:
                condition = _pop(self.stack)
                if type(condition) is not bool:
                    raise VMRuntimeError("Condition requires BOOL")
                if not condition:
                    self.ip = target
        elif op == "PRINT":
            self.output.append(_render(_pop(self.stack)))
        elif op == "POP":
            _pop(self.stack)
        else:
            raise VMRuntimeError(f"Unknown opcode {op!r}")
        return False


def execute(program: Program, *, step_limit: int = 100_000) -> list[str]:
    if type(step_limit) is not int or step_limit <= 0:
        raise ValueError("step_limit must be a positive int")
    machine = _Machine(program)
    for _ in range(step_limit):
        if machine._step():
            return machine.output
    raise StepLimitError(f"Step limit exceeded ({step_limit})")
