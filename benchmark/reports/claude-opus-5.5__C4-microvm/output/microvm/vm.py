"""Stack virtual machine and the runtime semantics of every operator."""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable

from .errors import StepLimitError, VMRuntimeError

if TYPE_CHECKING:  # avoids an import cycle: compiler -> optimizer -> vm
    from .compiler import Program

_UNSET = object()


def type_name(value: object) -> str:
    """Return the language-level type name of ``value``."""
    kind = type(value)
    if kind is bool:
        return "BOOL"
    if kind is int:
        return "INT"
    if kind is float:
        return "FLOAT"
    if kind is str:
        return "STRING"
    return kind.__name__


def _is_num(value: object) -> bool:
    # bool is deliberately excluded: it is not a number in this language.
    return type(value) is int or type(value) is float


def render(value: object) -> str:
    """Render a value the way ``print`` shows it."""
    if type(value) is bool:
        return "true" if value else "false"
    return str(value)


def _type_error(op: str, *values: object) -> VMRuntimeError:
    types = ", ".join(type_name(v) for v in values)
    return VMRuntimeError(f"unsupported operand type(s) for {op}: {types}")


def _numeric(op: str, a: object, b: object, fn: Callable[[object, object], object]) -> object:
    if not (_is_num(a) and _is_num(b)):
        raise _type_error(op, a, b)
    return fn(a, b)


def _add(a: object, b: object) -> object:
    if type(a) is str and type(b) is str:
        return a + b
    return _numeric("ADD", a, b, lambda x, y: x + y)


def _div(a: object, b: object) -> object:
    if not (_is_num(a) and _is_num(b)):
        raise _type_error("DIV", a, b)
    if b == 0:
        raise VMRuntimeError("division by zero")
    return float(a / b)


def _mod(a: object, b: object) -> object:
    if type(a) is not int or type(b) is not int:
        raise _type_error("MOD", a, b)
    if b == 0:
        raise VMRuntimeError("modulo by zero")
    return a % b


def _equal(a: object, b: object) -> bool:
    if (type(a) is bool) != (type(b) is bool):
        return False
    return bool(a == b)


def _ordered(op: str, fn: Callable[[object, object], bool]) -> Callable[[object, object], bool]:
    def compare(a: object, b: object) -> bool:
        if (_is_num(a) and _is_num(b)) or (type(a) is str and type(b) is str):
            return fn(a, b)
        raise _type_error(op, a, b)
    return compare


_BINARY: dict[str, Callable[[object, object], object]] = {
    "ADD": _add,
    "SUB": lambda a, b: _numeric("SUB", a, b, lambda x, y: x - y),
    "MUL": lambda a, b: _numeric("MUL", a, b, lambda x, y: x * y),
    "DIV": _div,
    "MOD": _mod,
    "EQ": _equal,
    "NE": lambda a, b: not _equal(a, b),
    "LT": _ordered("LT", lambda a, b: a < b),
    "LE": _ordered("LE", lambda a, b: a <= b),
    "GT": _ordered("GT", lambda a, b: a > b),
    "GE": _ordered("GE", lambda a, b: a >= b),
}


def binary_op(op: str, a: object, b: object) -> object:
    """Apply binary opcode ``op``; every failure is a ``VMRuntimeError``."""
    try:
        return _BINARY[op](a, b)
    except OverflowError as exc:
        raise VMRuntimeError(f"numeric overflow in {op}: {exc}") from None


def unary_op(op: str, a: object) -> object:
    """Apply unary opcode ``op`` (``NEG`` or ``NOT``)."""
    if op == "NEG":
        if not _is_num(a):
            raise _type_error("NEG", a)
        return -a
    if op == "NOT":
        if type(a) is not bool:
            raise _type_error("NOT", a)
        return not a
    raise VMRuntimeError(f"unknown unary opcode {op}")


class _Machine:
    def __init__(self, program: Program) -> None:
        self.program = program
        self.code = list(program.instructions)
        self.slots: list[object] = [_UNSET] * len(program.names)
        self.stack: list[object] = []
        self.output: list[str] = []

    def pop(self) -> object:
        if not self.stack:
            raise VMRuntimeError("stack underflow")
        return self.stack.pop()

    def index(self, arg: object, size: int, what: str) -> int:
        if type(arg) is not int or not 0 <= arg < size:
            raise VMRuntimeError(f"invalid {what} index {arg!r}")
        return arg

    def load(self, arg: object) -> None:
        slot = self.index(arg, len(self.slots), "variable")
        value = self.slots[slot]
        if value is _UNSET:
            raise VMRuntimeError(
                f"variable '{self.program.names[slot]}' read before assignment"
            )
        self.stack.append(value)

    def jump_if_false(self, arg: object, ip: int) -> int:
        cond = self.pop()
        if type(cond) is not bool:
            raise VMRuntimeError(f"condition must be BOOL, got {type_name(cond)}")
        return ip if cond else self.index(arg, len(self.code) + 1, "jump")

    def step(self, op: str, arg: object, ip: int) -> int:
        """Execute one instruction; return the next instruction pointer."""
        if op == "CONST":
            self.stack.append(self.program.constants[
                self.index(arg, len(self.program.constants), "constant")])
        elif op == "LOAD":
            self.load(arg)
        elif op == "STORE":
            self.slots[self.index(arg, len(self.slots), "variable")] = self.pop()
        elif op == "JUMP":
            return self.index(arg, len(self.code) + 1, "jump")
        elif op == "JUMP_IF_FALSE":
            return self.jump_if_false(arg, ip)
        elif op == "PRINT":
            self.output.append(render(self.pop()))
        elif op == "POP":
            self.pop()
        elif op in ("NEG", "NOT"):
            self.stack.append(unary_op(op, self.pop()))
        elif op in _BINARY:
            right = self.pop()
            left = self.pop()
            self.stack.append(binary_op(op, left, right))
        else:
            raise VMRuntimeError(f"unknown opcode {op!r}")
        return ip


def execute(program: Program, *, step_limit: int = 100_000) -> list[str]:
    """Run ``program`` and return its printed lines."""
    if type(step_limit) is not int or step_limit <= 0:
        raise ValueError("step_limit must be a positive int")
    machine = _Machine(program)
    code = machine.code
    ip = 0
    steps = 0
    while True:
        if not 0 <= ip < len(code):
            raise VMRuntimeError(f"instruction pointer {ip} out of range (missing HALT?)")
        steps += 1
        if steps > step_limit:
            raise StepLimitError(f"step limit of {step_limit} exceeded")
        instr = code[ip]
        if instr.op == "HALT":
            return machine.output
        ip = machine.step(instr.op, instr.arg, ip + 1)
