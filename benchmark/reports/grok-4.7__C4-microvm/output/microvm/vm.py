import dataclasses

from microvm.compiler import Instr, Program
from microvm.errors import StepLimitError, VMRuntimeError

_UNSET = object()
_BIN_OPS = {
    "ADD": "+",
    "SUB": "-",
    "MUL": "*",
    "DIV": "/",
    "MOD": "%",
    "EQ": "==",
    "NE": "!=",
    "LT": "<",
    "LE": "<=",
    "GT": ">",
    "GE": ">=",
}


@dataclasses.dataclass
class _State:
    program: Program
    stack: list[object]
    slots: list[object]
    output: list[str]
    ip: int
    steps: int


def execute(program: Program, *, step_limit: int = 100_000) -> list[str]:
    if type(step_limit) is not int or step_limit < 1:
        raise ValueError("step_limit must be a positive integer")
    state = _State(program, [], [_UNSET] * len(program.names), [], 0, 0)
    return _loop(state, step_limit)


def _loop(state: _State, step_limit: int) -> list[str]:
    code = state.program.instructions
    while True:
        if state.steps >= step_limit:
            raise StepLimitError("step limit exceeded")
        if state.ip < 0 or state.ip >= len(code):
            raise VMRuntimeError("invalid instruction pointer")
        instr = code[state.ip]
        state.steps += 1
        if instr.op == "HALT":
            return state.output
        if not _dispatch(state, instr):
            state.ip += 1


def _dispatch(state: _State, instr: Instr) -> bool:
    handler = _HANDLERS.get(instr.op)
    if handler is None:
        raise VMRuntimeError(f"unknown opcode: {instr.op}")
    return handler(state, instr)


def _apply_binary(op: str, left: object, right: object) -> object:
    if op in ("+", "-", "*"):
        return _arith(op, left, right)
    if op == "/":
        return _div(left, right)
    if op == "%":
        return _mod(left, right)
    if op in ("==", "!="):
        same = _equal(left, right)
        return same if op == "==" else not same
    if op in ("<", "<=", ">", ">="):
        return _ordered(op, left, right)
    raise VMRuntimeError(f"unknown operator: {op}")


def _apply_unary(op: str, value: object) -> object:
    if op == "-":
        return _neg(value)
    if op == "not":
        return _not(value)
    raise VMRuntimeError(f"unknown unary operator: {op}")


def _is_int(value: object) -> bool:
    return type(value) is int


def _is_float(value: object) -> bool:
    return type(value) is float


def _is_number(value: object) -> bool:
    return type(value) is int or type(value) is float


def _is_bool(value: object) -> bool:
    return type(value) is bool


def _is_str(value: object) -> bool:
    return type(value) is str


def _arith(op: str, left: object, right: object) -> object:
    if op == "+" and _is_str(left) and _is_str(right):
        return left + right
    if not _is_number(left) or not _is_number(right):
        raise VMRuntimeError(f"invalid operands for {op}")
    result = _raw_arith(op, left, right)
    if _is_int(left) and _is_int(right):
        return int(result)
    return float(result)


def _raw_arith(op: str, left: object, right: object) -> object:
    if op == "+":
        return left + right  # type: ignore[operator]
    if op == "-":
        return left - right  # type: ignore[operator]
    return left * right  # type: ignore[operator]


def _div(left: object, right: object) -> float:
    if not _is_number(left) or not _is_number(right):
        raise VMRuntimeError("invalid operands for /")
    if right == 0:
        raise VMRuntimeError("division by zero")
    return float(left) / float(right)  # type: ignore[arg-type]


def _mod(left: object, right: object) -> int:
    if not _is_int(left) or not _is_int(right):
        raise VMRuntimeError("invalid operands for %")
    if right == 0:
        raise VMRuntimeError("modulo by zero")
    return left % right  # type: ignore[operator]


def _equal(left: object, right: object) -> bool:
    if _is_bool(left) or _is_bool(right):
        return _is_bool(left) and _is_bool(right) and left == right
    if _is_number(left) and _is_number(right):
        return left == right
    if type(left) is type(right):
        return left == right
    return False


def _ordered(op: str, left: object, right: object) -> bool:
    numeric = _is_number(left) and _is_number(right)
    textual = _is_str(left) and _is_str(right)
    if not numeric and not textual:
        raise VMRuntimeError(f"invalid operands for {op}")
    return _cmp(op, left, right)


def _cmp(op: str, left: object, right: object) -> bool:
    if op == "<":
        return left < right  # type: ignore[operator]
    if op == "<=":
        return left <= right  # type: ignore[operator]
    if op == ">":
        return left > right  # type: ignore[operator]
    return left >= right  # type: ignore[operator]


def _neg(value: object) -> object:
    if _is_int(value) or _is_float(value):
        return -value  # type: ignore[operator]
    raise VMRuntimeError("unary minus requires a number")


def _not(value: object) -> object:
    if not _is_bool(value):
        raise VMRuntimeError("not requires a bool")
    return not value


def _render(value: object) -> str:
    if _is_bool(value):
        return "true" if value else "false"
    if _is_int(value) or _is_float(value) or _is_str(value):
        return str(value)
    raise VMRuntimeError("cannot print value")


def _pop(state: _State) -> object:
    if not state.stack:
        raise VMRuntimeError("stack underflow")
    return state.stack.pop()


def _arg(instr: Instr) -> int:
    if type(instr.arg) is not int:
        raise VMRuntimeError(f"{instr.op} missing argument")
    return instr.arg


def _check_slot(state: _State, index: int) -> None:
    if index < 0 or index >= len(state.slots):
        raise VMRuntimeError("variable index out of range")


def _op_const(state: _State, instr: Instr) -> bool:
    index = _arg(instr)
    if index < 0 or index >= len(state.program.constants):
        raise VMRuntimeError("constant index out of range")
    state.stack.append(state.program.constants[index])
    return False


def _op_load(state: _State, instr: Instr) -> bool:
    index = _arg(instr)
    _check_slot(state, index)
    value = state.slots[index]
    if value is _UNSET:
        name = state.program.names[index]
        raise VMRuntimeError(f"variable '{name}' is uninitialized")
    state.stack.append(value)
    return False


def _op_store(state: _State, instr: Instr) -> bool:
    index = _arg(instr)
    _check_slot(state, index)
    state.slots[index] = _pop(state)
    return False


def _op_binary(state: _State, instr: Instr) -> bool:
    right = _pop(state)
    left = _pop(state)
    state.stack.append(_apply_binary(_BIN_OPS[instr.op], left, right))
    return False


def _op_unary(state: _State, instr: Instr) -> bool:
    op = "-" if instr.op == "NEG" else "not"
    state.stack.append(_apply_unary(op, _pop(state)))
    return False


def _op_jump(state: _State, instr: Instr) -> bool:
    state.ip = _arg(instr)
    return True


def _op_jump_if_false(state: _State, instr: Instr) -> bool:
    cond = _pop(state)
    if type(cond) is not bool:
        raise VMRuntimeError("condition must be bool")
    if not cond:
        state.ip = _arg(instr)
        return True
    return False


def _op_print(state: _State, instr: Instr) -> bool:
    state.output.append(_render(_pop(state)))
    return False


def _op_pop(state: _State, instr: Instr) -> bool:
    _pop(state)
    return False


_HANDLERS = {
    "CONST": _op_const,
    "LOAD": _op_load,
    "STORE": _op_store,
    "ADD": _op_binary,
    "SUB": _op_binary,
    "MUL": _op_binary,
    "DIV": _op_binary,
    "MOD": _op_binary,
    "NEG": _op_unary,
    "NOT": _op_unary,
    "EQ": _op_binary,
    "NE": _op_binary,
    "LT": _op_binary,
    "LE": _op_binary,
    "GT": _op_binary,
    "GE": _op_binary,
    "JUMP": _op_jump,
    "JUMP_IF_FALSE": _op_jump_if_false,
    "PRINT": _op_print,
    "POP": _op_pop,
}
