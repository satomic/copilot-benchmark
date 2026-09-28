from .compiler import Instr, Program
from .errors import StepLimitError, VMRuntimeError


_UNSET = object()


def execute(program: Program, *, step_limit: int = 100_000) -> list[str]:
    if type(step_limit) is not int or step_limit <= 0:
        raise ValueError("step_limit must be a positive integer")
    values: list[object] = [_UNSET] * len(program.names)
    stack: list[object] = []
    output: list[str] = []
    ip = 0
    steps = 0
    while True:
        if ip < 0 or ip >= len(program.instructions):
            raise VMRuntimeError(f"instruction pointer out of range: {ip}")
        steps += 1
        if steps > step_limit:
            raise StepLimitError(f"instruction step limit exceeded ({step_limit})")
        instr = program.instructions[ip]
        ip = _execute_one(instr, program, values, stack, output, ip)
        if instr.op == "HALT":
            return output


def _execute_one(instr: Instr, program: Program, values: list[object],
                 stack: list[object], output: list[str], ip: int) -> int:
    op, arg = instr.op, instr.arg
    if op == "CONST":
        stack.append(_indexed(program.constants, arg, "constant"))
    elif op == "LOAD":
        value = _indexed(values, arg, "variable")
        if value is _UNSET:
            raise VMRuntimeError(f"variable {program.names[arg]} has not been assigned")
        stack.append(value)
    elif op == "STORE":
        values[arg] = _pop(stack)
    elif op == "PRINT":
        output.append(_render(_pop(stack)))
    elif op == "POP":
        _pop(stack)
    elif op in {"JUMP", "JUMP_IF_FALSE"}:
        if op == "JUMP":
            return _jump(arg, len(program.instructions))
        condition = _pop(stack)
        if type(condition) is not bool:
            raise VMRuntimeError("condition must be BOOL")
        if not condition:
            return _jump(arg, len(program.instructions))
    elif op in {"NEG", "NOT"}:
        stack.append(_unary(op, _pop(stack)))
    elif op in {"ADD", "SUB", "MUL", "DIV", "MOD", "EQ", "NE",
                "LT", "LE", "GT", "GE"}:
        right, left = _pop(stack), _pop(stack)
        stack.append(_binary(op, left, right))
    elif op == "HALT":
        return ip
    else:
        raise VMRuntimeError(f"unknown opcode {op!r}")
    return ip + 1


def _indexed(items: list, index: int | None, label: str) -> object:
    if type(index) is not int or not 0 <= index < len(items):
        raise VMRuntimeError(f"{label} index out of range: {index}")
    return items[index]


def _pop(stack: list[object]) -> object:
    if not stack:
        raise VMRuntimeError("stack underflow")
    return stack.pop()


def _jump(target: int | None, count: int) -> int:
    if type(target) is not int or not 0 <= target < count:
        raise VMRuntimeError(f"jump target out of range: {target}")
    return target


def _unary(op: str, value: object) -> object:
    if op == "NOT" and type(value) is bool:
        return not value
    if op == "NEG" and _number(value):
        return -value
    expected = "BOOL" if op == "NOT" else "number"
    raise VMRuntimeError(f"{op} requires {expected}")


def _binary(op: str, left: object, right: object) -> object:
    if op in {"EQ", "NE"}:
        equal = _equal(left, right)
        return equal if op == "EQ" else not equal
    if op in {"LT", "LE", "GT", "GE"}:
        if not _ordered(left, right):
            raise VMRuntimeError(f"{op} requires two numbers or two strings")
        return {"LT": left < right, "LE": left <= right,
                "GT": left > right, "GE": left >= right}[op]
    if op == "ADD" and type(left) is str and type(right) is str:
        return left + right
    if op not in {"ADD", "SUB", "MUL", "DIV", "MOD"}:
        raise VMRuntimeError(f"unknown binary opcode {op!r}")
    if not _number(left) or not _number(right):
        raise VMRuntimeError(f"{op} requires numeric operands")
    if op == "DIV":
        if right == 0:
            raise VMRuntimeError("division by zero")
        try:
            return left / right
        except OverflowError as exc:
            raise VMRuntimeError("numeric overflow") from exc
    if op == "MOD":
        if type(left) is not int or type(right) is not int:
            raise VMRuntimeError("MOD requires INT operands")
        if right == 0:
            raise VMRuntimeError("modulo by zero")
        return left % right
    try:
        return {"ADD": lambda: left + right, "SUB": lambda: left - right,
                "MUL": lambda: left * right}[op]()
    except OverflowError as exc:
        raise VMRuntimeError("numeric overflow") from exc


def _number(value: object) -> bool:
    return type(value) in {int, float}


def _equal(left: object, right: object) -> bool:
    if type(left) is type(right):
        return left == right
    return _number(left) and _number(right) and left == right


def _ordered(left: object, right: object) -> bool:
    return (_number(left) and _number(right)) or (
        type(left) is str and type(right) is str)


def _render(value: object) -> str:
    if type(value) is bool:
        return "true" if value else "false"
    return str(value)
