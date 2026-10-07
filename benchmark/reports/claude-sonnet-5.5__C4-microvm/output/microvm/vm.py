"""Stack virtual machine and the runtime semantics shared with the optimizer."""

from typing import Callable

from .errors import StepLimitError, VMRuntimeError


def _is_num(v: object) -> bool:
    return type(v) is int or type(v) is float


def _type_name(v: object) -> str:
    return {int: "INT", float: "FLOAT", str: "STRING", bool: "BOOL"}.get(type(v), "?")


def _need_nums(op: str, left: object, right: object) -> None:
    if not (_is_num(left) and _is_num(right)):
        raise VMRuntimeError(
            f"{op}: unsupported operands {_type_name(left)} and {_type_name(right)}"
        )


def _add(left: object, right: object) -> object:
    if type(left) is str and type(right) is str:
        return left + right
    _need_nums("ADD", left, right)
    return left + right  # type: ignore[operator]


def _sub(left: object, right: object) -> object:
    _need_nums("SUB", left, right)
    return left - right  # type: ignore[operator]


def _mul(left: object, right: object) -> object:
    _need_nums("MUL", left, right)
    return left * right  # type: ignore[operator]


def _div(left: object, right: object) -> object:
    _need_nums("DIV", left, right)
    if right == 0:
        raise VMRuntimeError("division by zero")
    return left / right  # type: ignore[operator]


def _mod(left: object, right: object) -> object:
    if type(left) is not int or type(right) is not int:
        raise VMRuntimeError("MOD requires two INT operands")
    if right == 0:
        raise VMRuntimeError("modulo by zero")
    return left % right


def _equal(left: object, right: object) -> bool:
    if _is_num(left) and _is_num(right):
        return left == right
    return type(left) is type(right) and left == right


def _ordered(op: str, left: object, right: object) -> None:
    both_str = type(left) is str and type(right) is str
    if not both_str:
        _need_nums(op, left, right)


def _lt(left: object, right: object) -> object:
    _ordered("LT", left, right)
    return left < right  # type: ignore[operator]


def _le(left: object, right: object) -> object:
    _ordered("LE", left, right)
    return left <= right  # type: ignore[operator]


def _gt(left: object, right: object) -> object:
    _ordered("GT", left, right)
    return left > right  # type: ignore[operator]


def _ge(left: object, right: object) -> object:
    _ordered("GE", left, right)
    return left >= right  # type: ignore[operator]


BINARY_FUNCS: dict[str, Callable[[object, object], object]] = {
    "ADD": _add, "SUB": _sub, "MUL": _mul, "DIV": _div, "MOD": _mod,
    "EQ": lambda a, b: _equal(a, b), "NE": lambda a, b: not _equal(a, b),
    "LT": _lt, "LE": _le, "GT": _gt, "GE": _ge,
}


def apply_binary(op: str, left: object, right: object) -> object:
    try:
        return BINARY_FUNCS[op](left, right)
    except (OverflowError, ValueError) as exc:
        raise VMRuntimeError(f"{op}: numeric error: {exc}") from None


def apply_neg(value: object) -> object:
    if not _is_num(value):
        raise VMRuntimeError(f"NEG: unsupported operand {_type_name(value)}")
    return -value  # type: ignore[operator]


def apply_not(value: object) -> object:
    if type(value) is not bool:
        raise VMRuntimeError(f"NOT: unsupported operand {_type_name(value)}")
    return not value


def render(value: object) -> str:
    if type(value) is bool:
        return "true" if value else "false"
    try:
        return str(value)
    except ValueError as exc:
        raise VMRuntimeError(f"PRINT: cannot render value: {exc}") from None


_UNSET = object()


class _Machine:
    def __init__(self, program: object, step_limit: int) -> None:
        self.program = program
        self.code = program.instructions  # type: ignore[attr-defined]
        self.slots: list = [_UNSET] * len(program.names)  # type: ignore[attr-defined]
        self.stack: list = []
        self.out: list[str] = []
        self.ip = 0
        self.steps = 0
        self.limit = step_limit

    def pop(self) -> object:
        if not self.stack:
            raise VMRuntimeError("stack underflow")
        return self.stack.pop()

    def slot(self, index: object) -> int:
        if type(index) is not int or not 0 <= index < len(self.slots):
            raise VMRuntimeError(f"invalid variable slot {index!r}")
        return index

    def jump(self, target: object) -> None:
        if type(target) is not int or not 0 <= target < len(self.code):
            raise VMRuntimeError(f"invalid jump target {target!r}")
        self.ip = target

    def do_const(self, arg: object) -> None:
        pool = self.program.constants  # type: ignore[attr-defined]
        if type(arg) is not int or not 0 <= arg < len(pool):
            raise VMRuntimeError(f"invalid constant index {arg!r}")
        self.stack.append(pool[arg])

    def do_load(self, arg: object) -> None:
        index = self.slot(arg)
        value = self.slots[index]
        if value is _UNSET:
            name = self.program.names[index]  # type: ignore[attr-defined]
            raise VMRuntimeError(f"variable {name!r} read before assignment")
        self.stack.append(value)

    def do_store(self, arg: object) -> None:
        index = self.slot(arg)
        self.slots[index] = self.pop()

    def do_jif(self, arg: object) -> None:
        cond = self.pop()
        if type(cond) is not bool:
            raise VMRuntimeError(f"condition must be BOOL, got {_type_name(cond)}")
        if not cond:
            self.jump(arg)

    def step(self) -> bool:
        if not 0 <= self.ip < len(self.code):
            raise VMRuntimeError("instruction pointer out of range")
        self.steps += 1
        if self.steps > self.limit:
            raise StepLimitError(f"step limit {self.limit} exceeded")
        instr = self.code[self.ip]
        self.ip += 1
        op, arg = instr.op, instr.arg
        if op in BINARY_FUNCS:
            right = self.pop()
            left = self.pop()
            self.stack.append(apply_binary(op, left, right))
        elif op == "CONST":
            self.do_const(arg)
        elif op == "LOAD":
            self.do_load(arg)
        elif op == "STORE":
            self.do_store(arg)
        elif op == "NEG":
            self.stack.append(apply_neg(self.pop()))
        elif op == "NOT":
            self.stack.append(apply_not(self.pop()))
        elif op == "JUMP":
            self.jump(arg)
        elif op == "JUMP_IF_FALSE":
            self.do_jif(arg)
        elif op == "PRINT":
            self.out.append(render(self.pop()))
        elif op == "POP":
            self.pop()
        elif op == "HALT":
            return False
        else:
            raise VMRuntimeError(f"unknown opcode {op!r}")
        return True


def execute(program: object, *, step_limit: int = 100_000) -> list[str]:
    if type(step_limit) is not int or step_limit <= 0:
        raise ValueError("step_limit must be a positive int")
    machine = _Machine(program, step_limit)
    while machine.step():
        pass
    return machine.out
