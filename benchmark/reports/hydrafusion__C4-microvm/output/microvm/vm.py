from .compiler import Program
from .errors import StepLimitError, VMRuntimeError


_UNSET = object()


def _is_number(value: object) -> bool:
    return type(value) in (int, float)


def _equal(left: object, right: object) -> bool:
    if _is_number(left) and _is_number(right):
        return left == right
    return type(left) is type(right) and left == right


def _arithmetic(op: str, left: object, right: object) -> object:
    if op == "ADD" and type(left) is str and type(right) is str:
        return left + right
    if op == "MOD":
        if type(left) is not int or type(right) is not int:
            raise VMRuntimeError("modulo requires integers")
        if right == 0:
            raise VMRuntimeError("modulo by zero")
        return left % right
    if not _is_number(left) or not _is_number(right):
        raise VMRuntimeError(f"{op.lower()} requires numbers")
    if op == "DIV" and right == 0:
        raise VMRuntimeError("division by zero")
    if op == "ADD":
        return left + right
    if op == "SUB":
        return left - right
    if op == "MUL":
        return left * right
    return left / right


def _comparison(op: str, left: object, right: object) -> bool:
    if op in ("EQ", "NE"):
        result = _equal(left, right)
        return result if op == "EQ" else not result
    valid = (_is_number(left) and _is_number(right)) or (
        type(left) is str and type(right) is str
    )
    if not valid:
        raise VMRuntimeError("ordered comparison requires two numbers or two strings")
    if op == "LT":
        return left < right
    if op == "LE":
        return left <= right
    if op == "GT":
        return left > right
    return left >= right


def _render(value: object) -> str:
    if type(value) is bool:
        return "true" if value else "false"
    return str(value)


def _pop(stack: list[object]) -> object:
    if not stack:
        raise VMRuntimeError("stack underflow")
    return stack.pop()


def _binary(stack: list[object], op: str) -> None:
    right = _pop(stack)
    left = _pop(stack)
    if op in ("ADD", "SUB", "MUL", "DIV", "MOD"):
        stack.append(_arithmetic(op, left, right))
    else:
        stack.append(_comparison(op, left, right))


def execute(program: Program, *, step_limit: int = 100_000) -> list[str]:
    if type(step_limit) is not int or step_limit <= 0:
        raise ValueError("step_limit must be a positive integer")
    slots: list[object] = [_UNSET] * len(program.names)
    stack: list[object] = []
    output: list[str] = []
    ip = 0
    steps = 0
    while ip < len(program.instructions):
        steps += 1
        if steps > step_limit:
            raise StepLimitError("step limit exceeded")
        instruction = program.instructions[ip]
        ip += 1
        op, arg = instruction.op, instruction.arg
        if op == "CONST":
            stack.append(program.constants[arg])
        elif op == "LOAD":
            value = slots[arg]
            if value is _UNSET:
                raise VMRuntimeError(f"variable {program.names[arg]} is unassigned")
            stack.append(value)
        elif op == "STORE":
            slots[arg] = _pop(stack)
        elif op in ("ADD", "SUB", "MUL", "DIV", "MOD", "EQ", "NE", "LT", "LE", "GT", "GE"):
            _binary(stack, op)
        elif op == "NEG":
            value = _pop(stack)
            if not _is_number(value):
                raise VMRuntimeError("negation requires a number")
            stack.append(-value)
        elif op == "NOT":
            value = _pop(stack)
            if type(value) is not bool:
                raise VMRuntimeError("not requires a boolean")
            stack.append(not value)
        elif op == "JUMP":
            ip = arg
        elif op == "JUMP_IF_FALSE":
            value = _pop(stack)
            if type(value) is not bool:
                raise VMRuntimeError("condition requires a boolean")
            if not value:
                ip = arg
        elif op == "PRINT":
            output.append(_render(_pop(stack)))
        elif op == "POP":
            _pop(stack)
        elif op == "HALT":
            return output
        else:
            raise VMRuntimeError(f"unknown opcode: {op}")
    raise VMRuntimeError("program terminated without HALT")
