"""Stack virtual machine and the runtime value semantics of the language."""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable

from .errors import StepLimitError, VMRuntimeError
from .opcodes import OPCODES

if TYPE_CHECKING:  # avoid an import cycle: compiler -> optimizer -> vm -> compiler
    from .compiler import Program


def is_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def type_name(value: object) -> str:
    if isinstance(value, bool):
        return "BOOL"
    if isinstance(value, int):
        return "INT"
    if isinstance(value, float):
        return "FLOAT"
    if isinstance(value, str):
        return "STRING"
    return type(value).__name__


def render(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _arith(op: str, left: object, right: object) -> object:
    if op == "+" and isinstance(left, str) and isinstance(right, str):
        return left + right
    if not (is_number(left) and is_number(right)):
        raise VMRuntimeError(
            f"unsupported operand types for {op}: {type_name(left)} and {type_name(right)}"
        )
    if op == "%" and not (isinstance(left, int) and isinstance(right, int)):
        raise VMRuntimeError("% requires two INT operands")
    if op in ("/", "%") and right == 0:
        raise VMRuntimeError("division by zero" if op == "/" else "modulo by zero")
    try:
        if op == "+":
            return left + right
        if op == "-":
            return left - right
        if op == "*":
            return left * right
        if op == "/":
            return left / right
        return left % right
    except OverflowError as exc:  # e.g. a huge INT divided into a FLOAT
        raise VMRuntimeError(f"arithmetic overflow in {op}: {exc}") from exc


def _equal(left: object, right: object) -> bool:
    if is_number(left) and is_number(right):
        return left == right
    if type(left) is not type(right):
        return False
    return left == right


def _order(op: str, left: object, right: object) -> bool:
    both_numbers = is_number(left) and is_number(right)
    both_strings = isinstance(left, str) and isinstance(right, str)
    if not (both_numbers or both_strings):
        raise VMRuntimeError(
            f"cannot compare {type_name(left)} and {type_name(right)} with {op}"
        )
    if op == "<":
        return left < right
    if op == "<=":
        return left <= right
    if op == ">":
        return left > right
    return left >= right


def binary_op(op: str, left: object, right: object) -> object:
    """Apply a strict (non-short-circuit) binary operator following section 1 rules."""
    if op in ("+", "-", "*", "/", "%"):
        return _arith(op, left, right)
    if op == "==":
        return _equal(left, right)
    if op == "!=":
        return not _equal(left, right)
    if op in ("<", "<=", ">", ">="):
        return _order(op, left, right)
    raise VMRuntimeError(f"unknown binary operator {op!r}")


def unary_op(op: str, operand: object) -> object:
    if op == "-":
        if not is_number(operand):
            raise VMRuntimeError(f"unary - requires a number, got {type_name(operand)}")
        return -operand
    if op == "not":
        require_bool(operand, "not")
        return not operand
    raise VMRuntimeError(f"unknown unary operator {op!r}")


def require_bool(value: object, context: str) -> None:
    if not isinstance(value, bool):
        raise VMRuntimeError(f"{context} requires BOOL, got {type_name(value)}")


_BINARY_OPS: dict[str, str] = {
    "ADD": "+", "SUB": "-", "MUL": "*", "DIV": "/", "MOD": "%",
    "EQ": "==", "NE": "!=", "LT": "<", "LE": "<=", "GT": ">", "GE": ">=",
}
_UNSET = object()


class _Machine:
    def __init__(self, program: Program) -> None:
        self.constants = program.constants
        self.names = program.names
        self.code = program.instructions
        self.slots: list[object] = [_UNSET] * len(program.names)
        self.stack: list[object] = []
        self.output: list[str] = []
        self.ip = 0

    def pop(self) -> object:
        if not self.stack:
            raise VMRuntimeError("stack underflow")
        return self.stack.pop()

    def op_const(self, arg: int) -> None:
        self.stack.append(self.constants[arg])

    def op_load(self, arg: int) -> None:
        value = self.slots[arg]
        if value is _UNSET:
            raise VMRuntimeError(f"variable {self.names[arg]!r} read before assignment")
        self.stack.append(value)

    def op_store(self, arg: int) -> None:
        self.slots[arg] = self.pop()

    def op_jump(self, arg: int) -> None:
        self.ip = arg

    def op_jump_if_false(self, arg: int) -> None:
        cond = self.pop()
        require_bool(cond, "condition")
        if not cond:
            self.ip = arg

    def op_print(self, arg: int) -> None:
        self.output.append(render(self.pop()))

    def op_pop(self, arg: int) -> None:
        self.pop()

    def op_neg(self, arg: int) -> None:
        self.stack.append(unary_op("-", self.pop()))

    def op_not(self, arg: int) -> None:
        self.stack.append(unary_op("not", self.pop()))

    def op_binary(self, opname: str) -> None:
        right = self.pop()
        left = self.pop()
        self.stack.append(binary_op(_BINARY_OPS[opname], left, right))

    def run(self, step_limit: int) -> list[str]:
        handlers: dict[str, Callable[[int], None]] = {
            "CONST": self.op_const, "LOAD": self.op_load, "STORE": self.op_store,
            "JUMP": self.op_jump, "JUMP_IF_FALSE": self.op_jump_if_false,
            "PRINT": self.op_print, "POP": self.op_pop,
            "NEG": self.op_neg, "NOT": self.op_not,
        }
        steps = 0
        code = self.code
        while True:
            if self.ip < 0 or self.ip >= len(code):
                raise VMRuntimeError(f"instruction pointer {self.ip} out of range")
            instr = code[self.ip]
            self.ip += 1
            steps += 1
            if steps > step_limit:
                raise StepLimitError(f"step limit of {step_limit} exceeded")
            op = instr.op
            if op == "HALT":
                return self.output
            if op in _BINARY_OPS:
                self.op_binary(op)
            elif op in handlers:
                handlers[op](instr.arg)  # type: ignore[arg-type]
            elif op in OPCODES:
                raise VMRuntimeError(f"unhandled opcode {op}")
            else:
                raise VMRuntimeError(f"unknown opcode {op!r}")


def execute(program: Program, *, step_limit: int = 100_000) -> list[str]:
    """Run ``program`` and return its printed lines."""
    if isinstance(step_limit, bool) or not isinstance(step_limit, int) or step_limit <= 0:
        raise ValueError("step_limit must be a positive int")
    return _Machine(program).run(step_limit)
