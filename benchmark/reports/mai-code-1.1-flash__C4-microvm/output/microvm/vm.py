from .compiler import Program
from .errors import StepLimitError, VMRuntimeError

_MISSING = object()


def _render_value(value: object) -> str:
    if type(value) is bool:
        return "true" if value else "false"
    return str(value)


def _is_number(value: object) -> bool:
    return type(value) in (int, float)


def _pop_two(stack: list[object]) -> tuple[object, object]:
    right = stack.pop()
    left = stack.pop()
    return left, right


def _cmp_values(op: str, left: object, right: object) -> bool:
    if _is_number(left) and _is_number(right):
        a = float(left)
        b = float(right)
        return {"<": a < b, "<=": a <= b, ">": a > b, ">=": a >= b}[op]
    if type(left) is str and type(right) is str:
        return {"<": left < right, "<=": left <= right, ">": left > right, ">=": left >= right}[op]
    raise VMRuntimeError("Invalid comparison operands")


def _eq_values(left: object, right: object) -> bool:
    if type(left) is bool or type(right) is bool:
        if type(left) is bool and type(right) is bool:
            return left == right
        return False
    if _is_number(left) and _is_number(right):
        return float(left) == float(right)
    if type(left) is str and type(right) is str:
        return left == right
    return left == right


def _apply_binary(op: str, left: object, right: object) -> object:
    if op == "ADD":
        if type(left) is str and type(right) is str:
            return left + right
        if _is_number(left) and _is_number(right):
            if type(left) is float or type(right) is float:
                return float(left) + float(right)
            return left + right
        raise VMRuntimeError("Invalid operands for +")
    if op == "SUB":
        if _is_number(left) and _is_number(right):
            if type(left) is float or type(right) is float:
                return float(left) - float(right)
            return left - right
        raise VMRuntimeError("Invalid operands for -")
    if op == "MUL":
        if _is_number(left) and _is_number(right):
            if type(left) is float or type(right) is float:
                return float(left) * float(right)
            return left * right
        raise VMRuntimeError("Invalid operands for *")
    if op == "DIV":
        if _is_number(left) and _is_number(right):
            if right == 0:
                raise VMRuntimeError("Division by zero")
            return float(left) / float(right)
        raise VMRuntimeError("Invalid operands for /")
    if op == "MOD":
        if type(left) is int and type(right) is int:
            if right == 0:
                raise VMRuntimeError("Modulo by zero")
            return left % right
        raise VMRuntimeError("Invalid operands for %")
    if op == "EQ":
        return _eq_values(left, right)
    if op == "NE":
        return not _eq_values(left, right)
    if op in {"LT", "LE", "GT", "GE"}:
        return _cmp_values({"LT": "<", "LE": "<=", "GT": ">", "GE": ">="}[op], left, right)
    raise VMRuntimeError(f"Unsupported opcode: {op}")


def _step(program: Program, ip: int, stack: list[object], memory: list[object], outputs: list[str]) -> int:
    instr = program.instructions[ip]
    op = instr.op
    if op == "CONST":
        stack.append(program.constants[instr.arg])
        return ip + 1
    if op == "LOAD":
        value = memory[instr.arg]
        if value is _MISSING:
            raise VMRuntimeError(f"Variable '{program.names[instr.arg]}' is not assigned")
        stack.append(value)
        return ip + 1
    if op == "STORE":
        memory[instr.arg] = stack.pop()
        return ip + 1
    if op in {"ADD", "SUB", "MUL", "DIV", "MOD", "EQ", "NE", "LT", "LE", "GT", "GE"}:
        left, right = _pop_two(stack)
        stack.append(_apply_binary(op, left, right))
        return ip + 1
    if op == "NEG":
        value = stack.pop()
        if not _is_number(value):
            raise VMRuntimeError("Unary - requires a number")
        stack.append(-value)
        return ip + 1
    if op == "NOT":
        value = stack.pop()
        if type(value) is not bool:
            raise VMRuntimeError("NOT requires a bool")
        stack.append(not value)
        return ip + 1
    if op == "JUMP":
        return instr.arg
    if op == "JUMP_IF_FALSE":
        value = stack.pop()
        if type(value) is not bool:
            raise VMRuntimeError("Condition must be bool")
        if not value:
            return instr.arg
        return ip + 1
    if op == "PRINT":
        outputs.append(_render_value(stack.pop()))
        return ip + 1
    if op == "POP":
        stack.pop()
        return ip + 1
    if op == "HALT":
        return len(program.instructions)
    raise VMRuntimeError(f"Unsupported opcode: {op}")


def execute(program: Program, *, step_limit: int = 100_000) -> list[str]:
    if type(step_limit) is not int or step_limit <= 0:
        raise ValueError("step_limit must be a positive int")
    stack: list[object] = []
    memory: list[object] = [_MISSING for _ in program.names]
    outputs: list[str] = []
    ip = 0
    steps = 0
    while ip < len(program.instructions):
        steps += 1
        if steps > step_limit:
            raise StepLimitError("Step limit exceeded")
        ip = _step(program, ip, stack, memory, outputs)
    return outputs
