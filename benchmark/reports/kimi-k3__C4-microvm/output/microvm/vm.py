"""Stack-based virtual machine executing compiled Programs."""

from .compiler import Program
from .errors import StepLimitError, VMRuntimeError

_UNSET = object()  # marker for declared-but-never-assigned slots

_OP_SYMBOLS = {
    "ADD": "+", "SUB": "-", "MUL": "*", "DIV": "/", "MOD": "%",
    "EQ": "==", "NE": "!=", "LT": "<", "LE": "<=", "GT": ">", "GE": ">=",
}


def is_number(value: object) -> bool:
    """True for INT/FLOAT values; BOOL is not a number in this language."""
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def render(value: object) -> str:
    """Render a value the way ``print`` does (section 1 rule 9)."""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def eval_binop(op: str, left: object, right: object) -> object:
    """Apply a binary operator under the section 1 run-time rules."""
    if op in ("==", "!="):
        eq = _equals(left, right)
        return eq if op == "==" else not eq
    if op in ("<", "<=", ">", ">="):
        return _compare(op, left, right)
    if op == "+" and isinstance(left, str) and isinstance(right, str):
        return left + right
    if op == "%":
        if not (type(left) is int and type(right) is int):
            raise VMRuntimeError("'%' requires two INT operands")
        if right == 0:
            raise VMRuntimeError("modulo by zero")
        return left % right
    if not (is_number(left) and is_number(right)):
        raise VMRuntimeError(f"operator {op!r} requires number operands")
    if op == "+":
        return left + right
    if op == "-":
        return left - right
    if op == "*":
        return left * right
    if right == 0:
        raise VMRuntimeError("division by zero")
    return left / right  # '/' always yields FLOAT


def _equals(left: object, right: object) -> bool:
    """Equality: INT/FLOAT compare numerically; BOOL differs from INT."""
    if is_number(left) and is_number(right):
        return left == right
    if type(left) is not type(right):
        return False
    return bool(left == right)


def _compare(op: str, left: object, right: object) -> bool:
    both_num = is_number(left) and is_number(right)
    both_str = isinstance(left, str) and isinstance(right, str)
    if not (both_num or both_str):
        raise VMRuntimeError(f"operator {op!r} requires two numbers or two strings")
    if op == "<":
        return bool(left < right)
    if op == "<=":
        return bool(left <= right)
    if op == ">":
        return bool(left > right)
    return bool(left >= right)


def eval_neg(value: object) -> object:
    """Unary minus requires a number."""
    if not is_number(value):
        raise VMRuntimeError("unary '-' requires a number")
    return -value


def eval_not(value: object) -> bool:
    """Logical not requires a BOOL."""
    if not isinstance(value, bool):
        raise VMRuntimeError("'not' requires a BOOL operand")
    return not value


def _require_bool(value: object, what: str) -> bool:
    if not isinstance(value, bool):
        raise VMRuntimeError(f"{what} requires a BOOL operand")
    return value


def _step(program: Program, stack: list, slots: list, ip: int, out: list[str]) -> int:
    """Execute one instruction; return the next instruction pointer."""
    ins = program.instructions[ip]
    op = ins.op
    if op == "HALT":
        return -1
    if op == "CONST":
        stack.append(program.constants[ins.arg])
    elif op == "LOAD":
        value = slots[ins.arg]
        if value is _UNSET:
            raise VMRuntimeError(
                f"variable {program.names[ins.arg]!r} was never assigned"
            )
        stack.append(value)
    elif op == "STORE":
        slots[ins.arg] = stack.pop()
    elif op == "PRINT":
        out.append(render(stack.pop()))
    elif op == "POP":
        stack.pop()
    elif op == "NEG":
        stack.append(eval_neg(stack.pop()))
    elif op == "NOT":
        stack.append(eval_not(stack.pop()))
    elif op == "JUMP":
        return int(ins.arg)
    elif op == "JUMP_IF_FALSE":
        if not _require_bool(stack.pop(), "JUMP_IF_FALSE"):
            return int(ins.arg)
    else:
        right = stack.pop()
        left = stack.pop()
        stack.append(eval_binop(_OP_SYMBOLS[op], left, right))
    return ip + 1


def execute(program: Program, *, step_limit: int = 100_000) -> list[str]:
    """Run ``program`` and return the printed lines in order."""
    if isinstance(step_limit, bool) or not isinstance(step_limit, int) or step_limit <= 0:
        raise ValueError("step_limit must be a positive int")
    stack: list = []
    slots: list = [_UNSET] * len(program.names)
    out: list[str] = []
    ip = 0
    steps = 0
    while ip >= 0:
        steps += 1
        if steps > step_limit:
            raise StepLimitError(f"step limit of {step_limit} exceeded")
        ip = _step(program, stack, slots, ip, out)
    return out
