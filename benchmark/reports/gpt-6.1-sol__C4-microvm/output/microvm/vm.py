from typing import TYPE_CHECKING
import operator

from .errors import StepLimitError, VMRuntimeError
from .opcodes import ARG_OPCODES, OPCODES
from .parser import Value

if TYPE_CHECKING:
    from .compiler import Program


_ARITHMETIC = {
    "ADD": operator.add, "SUB": operator.sub, "MUL": operator.mul,
    "DIV": operator.truediv, "MOD": operator.mod,
}
_ORDERING = {
    "LT": operator.lt, "LE": operator.le, "GT": operator.gt, "GE": operator.ge,
}


def _is_number(value: Value) -> bool:
    return type(value) in (int, float)


def require_bool(value: Value) -> bool:
    if type(value) is not bool:
        raise VMRuntimeError("Expected BOOL")
    assert isinstance(value, bool)
    return value


def unary_operation(op: str, value: Value) -> Value:
    if op == "NOT":
        return not require_bool(value)
    if op != "NEG" or not _is_number(value):
        raise VMRuntimeError(f"{op} requires a number")
    assert isinstance(value, (int, float))
    return -value


def binary_operation(op: str, left: Value, right: Value) -> Value:
    numbers = _is_number(left) and _is_number(right)
    strings = type(left) is str and type(right) is str
    if op in ("EQ", "NE"):
        equal = (type(left) is type(right) or numbers) and left == right
        return equal if op == "EQ" else not equal
    if op in _ORDERING:
        if not (numbers or strings):
            raise VMRuntimeError(f"{op} requires two numbers or two strings")
        return _ORDERING[op](left, right)
    if op == "ADD" and strings:
        assert isinstance(left, str) and isinstance(right, str)
        return left + right
    if op not in _ARITHMETIC or not numbers:
        raise VMRuntimeError(f"{op} requires two numbers")
    if op == "MOD" and (type(left) is not int or type(right) is not int):
        raise VMRuntimeError("MOD requires two INTs")
    if op in ("DIV", "MOD") and right == 0:
        raise VMRuntimeError("Division or modulo by zero")
    try:
        return _ARITHMETIC[op](left, right)
    except (OverflowError, ValueError) as error:
        raise VMRuntimeError(f"{op} failed: {error}") from error


def render(value: Value) -> str:
    if type(value) is bool:
        return "true" if value else "false"
    return str(value)


class _Machine:
    def __init__(self, program: "Program") -> None:
        self.program = program
        self.stack: list[Value] = []
        self.variables: dict[int, Value] = {}
        self.output: list[str] = []
        self.ip = 0

    def pop(self) -> Value:
        if not self.stack:
            raise VMRuntimeError("Stack underflow")
        return self.stack.pop()

    def slot(self, arg: int | None, length: int, label: str) -> int:
        if type(arg) is not int or not 0 <= arg < length:
            raise VMRuntimeError(f"Invalid {label} index: {arg}")
        return arg

    def instruction(self, op: str, arg: int | None) -> bool:
        if op not in OPCODES:
            raise VMRuntimeError(f"Unknown opcode: {op}")
        if (op in ARG_OPCODES and type(arg) is not int) or (
            op not in ARG_OPCODES and arg is not None
        ):
            raise VMRuntimeError(f"Invalid argument for {op}")
        if op == "HALT":
            return False
        if op == "CONST":
            index = self.slot(arg, len(self.program.constants), "constant")
            value = self.program.constants[index]
            if type(value) not in (int, float, str, bool):
                raise VMRuntimeError("Invalid constant type")
            self.stack.append(value)
        elif op in ("LOAD", "STORE"):
            index = self.slot(arg, len(self.program.names), "variable")
            if op == "STORE":
                self.variables[index] = self.pop()
            elif index not in self.variables:
                raise VMRuntimeError(f"Unassigned variable: {self.program.names[index]}")
            else:
                self.stack.append(self.variables[index])
        elif op in ("JUMP", "JUMP_IF_FALSE"):
            target = self.slot(arg, len(self.program.instructions), "jump")
            if op == "JUMP" or not require_bool(self.pop()):
                self.ip = target
        elif op == "PRINT":
            self.output.append(render(self.pop()))
        elif op == "POP":
            self.pop()
        elif op in ("NEG", "NOT"):
            self.stack.append(unary_operation(op, self.pop()))
        else:
            right, left = self.pop(), self.pop()
            self.stack.append(binary_operation(op, left, right))
        return True


def execute(program: "Program", *, step_limit: int = 100_000) -> list[str]:
    if type(step_limit) is not int or step_limit <= 0:
        raise ValueError("step_limit must be a positive int")
    machine = _Machine(program)
    steps = 0
    while True:
        steps += 1
        if steps > step_limit:
            raise StepLimitError(f"Step limit exceeded ({step_limit})")
        if not 0 <= machine.ip < len(program.instructions):
            raise VMRuntimeError("Instruction pointer out of bounds")
        instruction = program.instructions[machine.ip]
        machine.ip += 1
        if not machine.instruction(instruction.op, instruction.arg):
            return machine.output
