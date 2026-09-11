"""The stack VM, and the type-rule primitives shared with the optimizer."""

from __future__ import annotations

from .errors import StepLimitError, VMRuntimeError

__all__ = ["binary_op", "unary_neg", "logical_not", "render", "execute"]

_UNSET = object()  # slot value for declared-but-never-assigned variables


def _is_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _require_bool(value: object, where: str) -> bool:
    if not isinstance(value, bool):
        raise VMRuntimeError(f"{where} requires BOOL, got {type(value).__name__}")
    return value


def _eq(left: object, right: object) -> bool:
    """Equality that separates BOOL from INT but lets INT and FLOAT mix."""
    if isinstance(left, bool) or isinstance(right, bool):
        return isinstance(left, bool) and isinstance(right, bool) and left == right
    if _is_number(left) and _is_number(right):
        return left == right
    if isinstance(left, str) and isinstance(right, str):
        return left == right
    return False


def binary_op(op: str, left: object, right: object) -> object:
    """Apply one binary operator under the section 1 rules."""
    if op in ("==", "!="):
        same = _eq(left, right)
        return same if op == "==" else not same
    if op in ("<", "<=", ">", ">="):
        ordered = (_is_number(left) and _is_number(right)) or (
            isinstance(left, str) and isinstance(right, str))
        if not ordered:
            raise VMRuntimeError(f"cannot order {type(left).__name__} and {type(right).__name__}")
        table = {"<": left < right, "<=": left <= right, ">": left > right, ">=": left >= right}
        return table[op]
    if op == "+" and isinstance(left, str) and isinstance(right, str):
        return left + right
    if op == "%":
        if not (_is_number(left) and isinstance(left, int)
                and _is_number(right) and isinstance(right, int)):
            raise VMRuntimeError("% requires two INT operands")
        if right == 0:
            raise VMRuntimeError("modulo by zero")
        return left % right
    if not (_is_number(left) and _is_number(right)):
        raise VMRuntimeError(
            f"operator {op} requires numbers, got {type(left).__name__} and {type(right).__name__}")
    if op == "+":
        return left + right
    if op == "-":
        return left - right
    if op == "*":
        return left * right
    if float(right) == 0.0:
        raise VMRuntimeError("division by zero")
    return float(left) / float(right)


def unary_neg(value: object) -> object:
    if not _is_number(value):
        raise VMRuntimeError(f"unary - requires a number, got {type(value).__name__}")
    return -value


def logical_not(value: object) -> bool:
    return not _require_bool(value, "not")


def render(value: object) -> str:
    """The print format: lowercase booleans, str() for everything else."""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


_COMPARE_OPS = {"EQ": "==", "NE": "!=", "LT": "<", "LE": "<=", "GT": ">", "GE": ">="}
_ARITH_OPS = {"ADD": "+", "SUB": "-", "MUL": "*", "DIV": "/", "MOD": "%"}


def execute(program: object, *, step_limit: int = 100_000) -> list[str]:
    """Run ``program`` and return the printed lines."""
    if isinstance(step_limit, bool) or not isinstance(step_limit, int) or step_limit < 1:
        raise ValueError("step_limit must be a positive int")
    slots: list[object] = [_UNSET] * len(program.names)
    stack: list[object] = []
    output: list[str] = []
    pointer = 0
    steps = 0
    instructions = program.instructions
    while True:
        instr = instructions[pointer]
        pointer += 1
        steps += 1
        if steps > step_limit:
            raise StepLimitError(f"step limit of {step_limit} exceeded")
        op, arg = instr.op, instr.arg
        if op == "CONST":
            stack.append(program.constants[arg])
        elif op == "LOAD":
            value = slots[arg]
            if value is _UNSET:
                raise VMRuntimeError(f"variable {program.names[arg]!r} was never assigned")
            stack.append(value)
        elif op == "STORE":
            slots[arg] = stack.pop()
        elif op in _ARITH_OPS or op in _COMPARE_OPS:
            right = stack.pop()
            left = stack.pop()
            symbol = _ARITH_OPS.get(op) or _COMPARE_OPS[op]
            stack.append(binary_op(symbol, left, right))
        elif op == "NEG":
            stack.append(unary_neg(stack.pop()))
        elif op == "NOT":
            stack.append(logical_not(stack.pop()))
        elif op == "JUMP":
            pointer = arg
        elif op == "JUMP_IF_FALSE":
            if not _require_bool(stack.pop(), "condition"):
                pointer = arg
        elif op == "PRINT":
            output.append(render(stack.pop()))
        elif op == "POP":
            stack.pop()
        elif op == "HALT":
            return output
        else:  # pragma: no cover
            raise VMRuntimeError(f"unknown opcode {op}")
