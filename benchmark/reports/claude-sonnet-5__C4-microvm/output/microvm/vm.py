"""Stack virtual machine for microvm bytecode."""

from typing import TYPE_CHECKING

from .errors import StepLimitError, VMRuntimeError

if TYPE_CHECKING:
    from .compiler import Program

_UNSET = object()


def _is_bool(v: object) -> bool:
    return type(v) is bool


def _is_number(v: object) -> bool:
    return isinstance(v, (int, float)) and not _is_bool(v)


def _values_equal(left: object, right: object) -> bool:
    if _is_bool(left) or _is_bool(right):
        return _is_bool(left) and _is_bool(right) and left == right
    if _is_number(left) and _is_number(right):
        return left == right
    if isinstance(left, str) and isinstance(right, str):
        return left == right
    return False


def _apply_additive_like(op: str, left: object, right: object) -> object:
    if op == "+" and isinstance(left, str) and isinstance(right, str):
        return left + right
    if not (_is_number(left) and _is_number(right)):
        raise VMRuntimeError(f"operator {op!r} requires two numbers (or two strings for +)")
    if op == "+":
        result = left + right
    elif op == "-":
        result = left - right
    else:
        result = left * right
    if isinstance(left, float) or isinstance(right, float):
        return float(result)
    return int(result)


def _apply_div(left: object, right: object) -> float:
    if not (_is_number(left) and _is_number(right)):
        raise VMRuntimeError("operator '/' requires two numbers")
    if right == 0:
        raise VMRuntimeError("division by zero")
    return left / right


def _apply_mod(left: object, right: object) -> int:
    if not (type(left) is int and type(right) is int):
        raise VMRuntimeError("operator '%' requires two integers")
    if right == 0:
        raise VMRuntimeError("modulo by zero")
    return left % right


def _apply_order(op: str, left: object, right: object) -> bool:
    if _is_number(left) and _is_number(right):
        pass
    elif isinstance(left, str) and isinstance(right, str):
        pass
    else:
        raise VMRuntimeError(f"operator {op!r} requires two numbers or two strings")
    if op == "<":
        return left < right
    if op == "<=":
        return left <= right
    if op == ">":
        return left > right
    return left >= right


def apply_binary(op: str, left: object, right: object) -> object:
    """Apply a binary operator's runtime semantics; shared by the VM and the optimizer."""
    if op in ("+", "-", "*"):
        return _apply_additive_like(op, left, right)
    if op == "/":
        return _apply_div(left, right)
    if op == "%":
        return _apply_mod(left, right)
    if op == "==":
        return _values_equal(left, right)
    if op == "!=":
        return not _values_equal(left, right)
    return _apply_order(op, left, right)


def apply_neg(value: object) -> object:
    if not _is_number(value):
        raise VMRuntimeError("unary '-' requires a number")
    return -value


def apply_not(value: object) -> bool:
    if not _is_bool(value):
        raise VMRuntimeError("'not' requires a bool")
    return not value


def render(value: object) -> str:
    if _is_bool(value):
        return "true" if value else "false"
    return str(value)


_BINOP_OPCODES = frozenset({"ADD", "SUB", "MUL", "DIV", "MOD", "EQ", "NE", "LT", "LE", "GT", "GE"})
_BINOP_SYMBOL = {
    "ADD": "+", "SUB": "-", "MUL": "*", "DIV": "/", "MOD": "%",
    "EQ": "==", "NE": "!=", "LT": "<", "LE": "<=", "GT": ">", "GE": ">=",
}


def _run_binop(op: str, stack: list) -> None:
    right = stack.pop()
    left = stack.pop()
    stack.append(apply_binary(_BINOP_SYMBOL[op], left, right))


def _exec_instr(instr: object, ip: int, ctx: dict) -> int:
    op = instr.op
    stack: list = ctx["stack"]
    if op == "CONST":
        stack.append(ctx["constants"][instr.arg])
    elif op == "LOAD":
        value = ctx["vars"][instr.arg]
        if value is _UNSET:
            raise VMRuntimeError(f"variable {ctx['names'][instr.arg]!r} used before assignment")
        stack.append(value)
    elif op == "STORE":
        ctx["vars"][instr.arg] = stack.pop()
    elif op in _BINOP_OPCODES:
        _run_binop(op, stack)
    elif op == "NEG":
        stack.append(apply_neg(stack.pop()))
    elif op == "NOT":
        stack.append(apply_not(stack.pop()))
    elif op == "JUMP":
        return instr.arg
    elif op == "JUMP_IF_FALSE":
        cond = stack.pop()
        if not _is_bool(cond):
            raise VMRuntimeError("condition must be a bool")
        if not cond:
            return instr.arg
    elif op == "PRINT":
        ctx["output"].append(render(stack.pop()))
    elif op == "POP":
        stack.pop()
    return ip + 1


def execute(program: "Program", *, step_limit: int = 100_000) -> list[str]:
    if not isinstance(step_limit, int) or isinstance(step_limit, bool) or step_limit <= 0:
        raise ValueError("step_limit must be a positive int")
    ctx = {
        "stack": [],
        "vars": [_UNSET] * len(program.names),
        "constants": program.constants,
        "names": program.names,
        "output": [],
    }
    instrs = program.instructions
    ip = 0
    steps = 0
    while True:
        instr = instrs[ip]
        steps += 1
        if steps > step_limit:
            raise StepLimitError("step limit exceeded")
        if instr.op == "HALT":
            break
        ip = _exec_instr(instr, ip, ctx)
    return ctx["output"]
