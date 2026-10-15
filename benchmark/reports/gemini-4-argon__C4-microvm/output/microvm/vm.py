from __future__ import annotations

from microvm.compiler import Program
from microvm.errors import StepLimitError, VMRuntimeError

_UNASSIGNED = object()


def _is_num(val: object) -> bool:
    return type(val) in (int, float)


def _format_val(val: object) -> str:
    if type(val) is bool:
        return "true" if val else "false"
    if type(val) in (int, float):
        return str(val)
    if type(val) is str:
        return val
    raise VMRuntimeError(f"Unsupported value type {type(val).__name__}")


def _exec_arith(op: str, left: object, right: object) -> object:
    if op == "ADD" and type(left) is str and type(right) is str:
        return left + right
    if not (_is_num(left) and _is_num(right)):
        raise VMRuntimeError(f"{op} requires numeric operands")
    if op == "ADD":
        return left + right  # type: ignore[operator]
    if op == "SUB":
        return left - right  # type: ignore[operator]
    if op == "MUL":
        return left * right  # type: ignore[operator]
    if op == "DIV":
        if right == 0:
            raise VMRuntimeError("Division by zero")
        return float(left) / float(right)  # type: ignore[arg-type]
    if op == "MOD":
        if type(left) is not int or type(right) is not int:
            raise VMRuntimeError("MOD requires integer operands")
        if right == 0:
            raise VMRuntimeError("Modulo by zero")
        return left % right
    raise VMRuntimeError(f"Unknown arithmetic op {op}")


def _exec_cmp(op: str, left: object, right: object) -> bool:
    if op in ("EQ", "NE"):
        if _is_num(left) and _is_num(right):
            eq = left == right
        elif type(left) is type(right):
            eq = left == right
        else:
            eq = False
        return eq if op == "EQ" else not eq
    if (_is_num(left) and _is_num(right)) or (type(left) is str and type(right) is str):
        if op == "LT":
            return bool(left < right)  # type: ignore[operator]
        if op == "LE":
            return bool(left <= right)  # type: ignore[operator]
        if op == "GT":
            return bool(left > right)  # type: ignore[operator]
        if op == "GE":
            return bool(left >= right)  # type: ignore[operator]
    raise VMRuntimeError(f"{op} requires two numbers or two strings")


def _exec_unary(op: str, val: object) -> object:
    if op == "NEG":
        if not _is_num(val):
            raise VMRuntimeError("NEG requires a numeric operand")
        return -val  # type: ignore[operator]
    if op == "NOT":
        if type(val) is not bool:
            raise VMRuntimeError("NOT requires a boolean operand")
        return not val
    raise VMRuntimeError(f"Unknown unary op {op}")


def _check_slot(arg: int | None, n_slots: int) -> int:
    if arg is None or not (0 <= arg < n_slots):
        raise VMRuntimeError(f"Invalid variable slot {arg!r}")
    return arg


def _check_const(arg: int | None, n_consts: int) -> int:
    if arg is None or not (0 <= arg < n_consts):
        raise VMRuntimeError(f"Invalid constant index {arg!r}")
    return arg


def _pop(stack: list[object]) -> object:
    if not stack:
        raise VMRuntimeError("Stack underflow")
    return stack.pop()


def _pop2(stack: list[object]) -> tuple[object, object]:
    if len(stack) < 2:
        raise VMRuntimeError("Stack underflow")
    right = stack.pop()
    left = stack.pop()
    return left, right


def execute(program: Program, *, step_limit: int = 100_000) -> list[str]:
    if type(step_limit) is not int or step_limit <= 0:
        raise ValueError("step_limit must be a positive int")
    instrs, consts, names = program.instructions, program.constants, program.names
    slots: list[object] = [_UNASSIGNED] * len(names)
    stack: list[object] = []
    output: list[str] = []
    ip, steps, n_instrs = 0, 0, len(instrs)

    while 0 <= ip < n_instrs:
        steps += 1
        if steps > step_limit:
            raise StepLimitError(f"Execution exceeded step limit of {step_limit}")
        ins = instrs[ip]
        op, arg = ins.op, ins.arg
        ip += 1

        if op == "CONST":
            stack.append(consts[_check_const(arg, len(consts))])
        elif op == "LOAD":
            slot = _check_slot(arg, len(slots))
            if slots[slot] is _UNASSIGNED:
                raise VMRuntimeError(f"Variable {names[slot]!r} read before assignment")
            stack.append(slots[slot])
        elif op == "STORE":
            slots[_check_slot(arg, len(slots))] = _pop(stack)
        elif op in ("ADD", "SUB", "MUL", "DIV", "MOD"):
            stack.append(_exec_arith(op, *_pop2(stack)))
        elif op in ("EQ", "NE", "LT", "LE", "GT", "GE"):
            stack.append(_exec_cmp(op, *_pop2(stack)))
        elif op in ("NEG", "NOT"):
            stack.append(_exec_unary(op, _pop(stack)))
        elif op == "JUMP":
            if arg is None:
                raise VMRuntimeError("JUMP missing target")
            ip = arg
        elif op == "JUMP_IF_FALSE":
            cond = _pop(stack)
            if type(cond) is not bool or arg is None:
                raise VMRuntimeError("Condition must be a boolean")
            if not cond:
                ip = arg
        elif op == "PRINT":
            output.append(_format_val(_pop(stack)))
        elif op == "POP":
            _pop(stack)
        elif op == "HALT":
            return output
        else:
            raise VMRuntimeError(f"Unknown opcode {op!r}")
    raise VMRuntimeError("Execution terminated without HALT")
