"""The stack virtual machine and the shared runtime value semantics.

The helpers in this module are the single source of truth for the language's
runtime rules; the optimizer reuses them so that folding can never disagree
with execution.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable

from .errors import StepLimitError, VMRuntimeError

if TYPE_CHECKING:  # pragma: no cover - import cycle avoidance only
    from .compiler import Instr, Program


def is_number(value: object) -> bool:
    """Return whether *value* counts as a number (``bool`` is not a number)."""
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def render(value: object) -> str:
    """Render *value* the way ``print`` does."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        return value
    return str(value)


def type_name(value: object) -> str:
    """Return the language level type name of *value*."""
    if isinstance(value, bool):
        return "BOOL"
    if isinstance(value, int):
        return "INT"
    if isinstance(value, float):
        return "FLOAT"
    if isinstance(value, str):
        return "STRING"
    return type(value).__name__


def _require_numbers(op: str, left: object, right: object) -> None:
    if not (is_number(left) and is_number(right)):
        raise VMRuntimeError(
            f"{op} requires numbers, got {type_name(left)} and {type_name(right)}"
        )


def op_add(left: object, right: object) -> object:
    if isinstance(left, str) and isinstance(right, str):
        return left + right
    _require_numbers("+", left, right)
    return left + right  # type: ignore[operator]


def op_sub(left: object, right: object) -> object:
    _require_numbers("-", left, right)
    return left - right  # type: ignore[operator]


def op_mul(left: object, right: object) -> object:
    _require_numbers("*", left, right)
    return left * right  # type: ignore[operator]


def op_div(left: object, right: object) -> object:
    _require_numbers("/", left, right)
    if right == 0:
        raise VMRuntimeError("division by zero")
    try:
        return left / right  # type: ignore[operator]
    except OverflowError as exc:  # e.g. huge int operands
        raise VMRuntimeError(f"division overflowed: {exc}") from exc


def op_mod(left: object, right: object) -> object:
    if not (isinstance(left, int) and isinstance(right, int)):
        raise VMRuntimeError("% requires two INTs")
    if isinstance(left, bool) or isinstance(right, bool):
        raise VMRuntimeError("% requires two INTs")
    if right == 0:
        raise VMRuntimeError("modulo by zero")
    return left % right


def values_equal(left: object, right: object) -> bool:
    """Structural equality that never raises; BOOL never equals a number."""
    if isinstance(left, bool) or isinstance(right, bool):
        return isinstance(left, bool) and isinstance(right, bool) and left == right
    if is_number(left) and is_number(right):
        return left == right
    if isinstance(left, str) and isinstance(right, str):
        return left == right
    return False


def op_eq(left: object, right: object) -> object:
    return values_equal(left, right)


def op_ne(left: object, right: object) -> object:
    return not values_equal(left, right)


def _ordered(op: str, left: object, right: object) -> tuple[object, object]:
    if is_number(left) and is_number(right):
        return left, right
    if isinstance(left, str) and isinstance(right, str):
        return left, right
    raise VMRuntimeError(
        f"{op} requires two numbers or two STRINGs, "
        f"got {type_name(left)} and {type_name(right)}"
    )


def op_lt(left: object, right: object) -> object:
    a, b = _ordered("<", left, right)
    return a < b  # type: ignore[operator]


def op_le(left: object, right: object) -> object:
    a, b = _ordered("<=", left, right)
    return a <= b  # type: ignore[operator]


def op_gt(left: object, right: object) -> object:
    a, b = _ordered(">", left, right)
    return a > b  # type: ignore[operator]


def op_ge(left: object, right: object) -> object:
    a, b = _ordered(">=", left, right)
    return a >= b  # type: ignore[operator]


def op_neg(value: object) -> object:
    if not is_number(value):
        raise VMRuntimeError(f"unary - requires a number, got {type_name(value)}")
    return -value  # type: ignore[operator]


def op_not(value: object) -> object:
    if not isinstance(value, bool):
        raise VMRuntimeError(f"not requires a BOOL, got {type_name(value)}")
    return not value


BINARY_OPS: dict[str, Callable[[object, object], object]] = {
    "ADD": op_add,
    "SUB": op_sub,
    "MUL": op_mul,
    "DIV": op_div,
    "MOD": op_mod,
    "EQ": op_eq,
    "NE": op_ne,
    "LT": op_lt,
    "LE": op_le,
    "GT": op_gt,
    "GE": op_ge,
}

UNARY_OPS: dict[str, Callable[[object], object]] = {"NEG": op_neg, "NOT": op_not}

_MISSING = object()


class _Machine:
    """Mutable execution state for a single :func:`execute` call."""

    def __init__(self, program: "Program", step_limit: int) -> None:
        self.program: "Program" = program
        self.step_limit: int = step_limit
        self.stack: list[object] = []
        self.slots: list[object] = [_MISSING] * len(program.names)
        self.output: list[str] = []
        self.ip: int = 0
        self.steps: int = 0

    def pop(self) -> object:
        if not self.stack:
            raise VMRuntimeError("stack underflow")
        return self.stack.pop()

    def fetch(self) -> "Instr":
        if not 0 <= self.ip < len(self.program.instructions):
            raise VMRuntimeError(f"instruction pointer out of range: {self.ip}")
        instr = self.program.instructions[self.ip]
        self.ip += 1
        return instr

    def constant(self, index: int | None) -> object:
        if index is None or not 0 <= index < len(self.program.constants):
            raise VMRuntimeError(f"constant index out of range: {index}")
        return self.program.constants[index]

    def slot(self, index: int | None) -> int:
        if index is None or not 0 <= index < len(self.slots):
            raise VMRuntimeError(f"variable slot out of range: {index}")
        return index

    def load(self, index: int | None) -> object:
        position = self.slot(index)
        value = self.slots[position]
        if value is _MISSING:
            name = self.program.names[position]
            raise VMRuntimeError(f"variable {name!r} used before it was assigned")
        return value

    def jump_target(self, arg: int | None) -> int:
        if arg is None or not 0 <= arg <= len(self.program.instructions):
            raise VMRuntimeError(f"jump target out of range: {arg}")
        return arg

    def condition(self) -> bool:
        value = self.pop()
        if not isinstance(value, bool):
            raise VMRuntimeError(f"condition must be BOOL, got {type_name(value)}")
        return value

    def run(self) -> list[str]:
        while True:
            if self.steps >= self.step_limit:
                raise StepLimitError(f"step limit of {self.step_limit} exceeded")
            self.steps += 1
            instr = self.fetch()
            op, arg = instr.op, instr.arg
            if op == "CONST":
                self.stack.append(self.constant(arg))
            elif op == "LOAD":
                self.stack.append(self.load(arg))
            elif op == "STORE":
                self.slots[self.slot(arg)] = self.pop()
            elif op == "JUMP":
                self.ip = self.jump_target(arg)
            elif op == "JUMP_IF_FALSE":
                target = self.jump_target(arg)
                if not self.condition():
                    self.ip = target
            elif op == "PRINT":
                self.output.append(render(self.pop()))
            elif op == "POP":
                self.pop()
            elif op == "HALT":
                return self.output
            elif op in UNARY_OPS:
                self.stack.append(UNARY_OPS[op](self.pop()))
            elif op in BINARY_OPS:
                right = self.pop()
                left = self.pop()
                self.stack.append(BINARY_OPS[op](left, right))
            else:
                raise VMRuntimeError(f"unknown opcode {op!r}")


def execute(program: "Program", *, step_limit: int = 100_000) -> list[str]:
    """Execute *program* and return the lines it printed."""
    if isinstance(step_limit, bool) or not isinstance(step_limit, int):
        raise ValueError("step_limit must be a positive int")
    if step_limit <= 0:
        raise ValueError("step_limit must be a positive int")
    return _Machine(program, step_limit).run()
