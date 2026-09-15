from __future__ import annotations

from microvm.compiler import Instr, Program
from microvm.errors import StepLimitError, VMRuntimeError

_UNSET = object()


def execute(program: Program, *, step_limit: int = 100_000) -> list[str]:
    if type(step_limit) is not int or step_limit <= 0:
        raise ValueError("step_limit must be a positive int")
    return _Machine(program).run(step_limit)


def is_num(value: object) -> bool:
    return type(value) is int or type(value) is float


def format_value(value: object) -> str:
    if type(value) is bool:
        return "true" if value else "false"
    if type(value) is str:
        return value
    return str(value)


def values_equal(left: object, right: object) -> bool:
    if type(left) is bool or type(right) is bool:
        return type(left) is bool and type(right) is bool and left is right
    if is_num(left) and is_num(right):
        return bool(left == right)
    return type(left) is type(right) and left == right


class _Machine:
    def __init__(self, program: Program) -> None:
        self.program = program
        self.stack: list[object] = []
        self.slots: list[object] = [_UNSET] * len(program.names)
        self.output: list[str] = []

    def run(self, step_limit: int) -> list[str]:
        ip = 0
        steps = 0
        code = self.program.instructions
        while 0 <= ip < len(code):
            instr = code[ip]
            steps += 1
            if steps > step_limit:
                raise StepLimitError("step limit exceeded")
            ip = self._step(instr, ip)
        return self.output

    def _step(self, instr: Instr, ip: int) -> int:
        op = instr.op
        if op == "HALT":
            return -1
        if op == "JUMP":
            return int(instr.arg)  # type: ignore[arg-type]
        if op == "JUMP_IF_FALSE":
            return self._jump_if_false(instr, ip)
        self._dispatch(instr)
        return ip + 1

    def _jump_if_false(self, instr: Instr, ip: int) -> int:
        cond = self._pop()
        if type(cond) is not bool:
            raise VMRuntimeError("condition must be bool")
        if not cond:
            return int(instr.arg)  # type: ignore[arg-type]
        return ip + 1

    def _dispatch(self, instr: Instr) -> None:
        op = instr.op
        if op == "CONST":
            self.stack.append(self.program.constants[int(instr.arg)])  # type: ignore[arg-type]
        elif op == "LOAD":
            self._load(int(instr.arg))  # type: ignore[arg-type]
        elif op == "STORE":
            self.slots[int(instr.arg)] = self._pop()  # type: ignore[index]
        elif op == "PRINT":
            self.output.append(format_value(self._pop()))
        elif op == "POP":
            self._pop()
        elif op == "NEG":
            self._neg()
        elif op == "NOT":
            self._not()
        else:
            self._bin(op)

    def _load(self, index: int) -> None:
        value = self.slots[index]
        if value is _UNSET:
            raise VMRuntimeError(f"unassigned variable {self.program.names[index]}")
        self.stack.append(value)

    def _pop(self) -> object:
        if not self.stack:
            raise VMRuntimeError("stack underflow")
        return self.stack.pop()

    def _neg(self) -> None:
        value = self._pop()
        if not is_num(value):
            raise VMRuntimeError("unary minus requires a number")
        self.stack.append(-value)  # type: ignore[operator]

    def _not(self) -> None:
        value = self._pop()
        if type(value) is not bool:
            raise VMRuntimeError("not requires bool")
        self.stack.append(not value)

    def _bin(self, op: str) -> None:
        right = self._pop()
        left = self._pop()
        if op == "ADD":
            self.stack.append(_add(left, right))
        elif op == "SUB":
            self.stack.append(_arith("-", left, right))
        elif op == "MUL":
            self.stack.append(_arith("*", left, right))
        elif op == "DIV":
            self.stack.append(_div(left, right))
        elif op == "MOD":
            self.stack.append(_mod(left, right))
        elif op in {"EQ", "NE", "LT", "LE", "GT", "GE"}:
            self.stack.append(_compare(op, left, right))
        else:
            raise VMRuntimeError(f"unknown opcode {op}")


def _add(left: object, right: object) -> object:
    if type(left) is str and type(right) is str:
        return left + right
    return _arith("+", left, right)


def _arith(op: str, left: object, right: object) -> object:
    if not (is_num(left) and is_num(right)):
        raise VMRuntimeError(f"{op} requires numbers")
    if op == "+":
        return left + right  # type: ignore[operator]
    if op == "-":
        return left - right  # type: ignore[operator]
    return left * right  # type: ignore[operator]


def _div(left: object, right: object) -> float:
    if not (is_num(left) and is_num(right)):
        raise VMRuntimeError("division requires numbers")
    if right == 0:
        raise VMRuntimeError("division by zero")
    return float(left) / float(right)


def _mod(left: object, right: object) -> int:
    if type(left) is not int or type(right) is not int:
        raise VMRuntimeError("modulo requires ints")
    if right == 0:
        raise VMRuntimeError("modulo by zero")
    return left % right


def _compare(op: str, left: object, right: object) -> bool:
    if op == "EQ":
        return values_equal(left, right)
    if op == "NE":
        return not values_equal(left, right)
    ok_num = is_num(left) and is_num(right)
    ok_str = type(left) is str and type(right) is str
    if not (ok_num or ok_str):
        raise VMRuntimeError("invalid comparison")
    if op == "LT":
        return bool(left < right)  # type: ignore[operator]
    if op == "LE":
        return bool(left <= right)  # type: ignore[operator]
    if op == "GT":
        return bool(left > right)  # type: ignore[operator]
    return bool(left >= right)  # type: ignore[operator]
