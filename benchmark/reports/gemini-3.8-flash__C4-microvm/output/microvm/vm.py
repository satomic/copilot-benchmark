"""Stack virtual machine for microvm."""

from microvm.compiler import Program
from microvm.errors import StepLimitError, VMRuntimeError
from microvm.optimizer import is_num, vm_equals

_UNSET: object = object()


def _format_print_value(val: object) -> str:
    if type(val) is bool:
        return "true" if val else "false"
    if type(val) is int or type(val) is float:
        return str(val)
    if type(val) is str:
        return val
    return str(val)


def _exec_arithmetic(op: str, left: object, right: object) -> object:
    if op == "ADD":
        if type(left) is str and type(right) is str:
            return left + right
        if is_num(left) and is_num(right):
            res = left + right  # type: ignore[operator]
            return int(res) if (type(left) is int and type(right) is int) else float(res)
        raise VMRuntimeError("Operands to '+' must be two numbers or two strings")
    if op in ("SUB", "MUL"):
        if is_num(left) and is_num(right):
            res = (left - right) if op == "SUB" else (left * right)  # type: ignore[operator]
            return int(res) if (type(left) is int and type(right) is int) else float(res)
        raise VMRuntimeError(f"Operands to '{op}' must be numbers")
    if op == "DIV":
        if is_num(left) and is_num(right):
            if right == 0:
                raise VMRuntimeError("Division by zero")
            return float(left) / float(right)  # type: ignore[arg-type]
        raise VMRuntimeError("Operands to '/' must be numbers")
    if op == "MOD":
        if type(left) is int and type(right) is int and type(left) is not bool and type(right) is not bool:
            if right == 0:
                raise VMRuntimeError("Modulo by zero")
            return left % right
        raise VMRuntimeError("Operands to '%' must be integers")
    raise VMRuntimeError(f"Unknown arithmetic opcode {op}")


def _exec_comparison(op: str, left: object, right: object) -> bool:
    if op == "EQ":
        return vm_equals(left, right)
    if op == "NE":
        return not vm_equals(left, right)
    if is_num(left) and is_num(right):
        if op == "LT":
            return left < right  # type: ignore[operator]
        if op == "LE":
            return left <= right  # type: ignore[operator]
        if op == "GT":
            return left > right  # type: ignore[operator]
        if op == "GE":
            return left >= right  # type: ignore[operator]
    if type(left) is str and type(right) is str:
        if op == "LT":
            return left < right
        if op == "LE":
            return left <= right
        if op == "GT":
            return left > right
        if op == "GE":
            return left >= right
    raise VMRuntimeError(f"Invalid operands for comparison {op}")


def _dispatch_instr(
    op: str,
    arg: int | None,
    stack: list[object],
    slots: list[object],
    program: Program,
    output: list[str],
    pc: int,
) -> int:
    if op == "CONST":
        stack.append(program.constants[arg])  # type: ignore[index]
        return pc + 1
    if op == "LOAD":
        val = slots[arg]  # type: ignore[index]
        if val is _UNSET:
            raise VMRuntimeError(f"Variable '{program.names[arg]}' was never assigned")  # type: ignore[index]
        stack.append(val)
        return pc + 1
    if op == "STORE":
        slots[arg] = stack.pop()  # type: ignore[index]
        return pc + 1
    if op in ("ADD", "SUB", "MUL", "DIV", "MOD"):
        right = stack.pop()
        left = stack.pop()
        stack.append(_exec_arithmetic(op, left, right))
        return pc + 1
    if op in ("EQ", "NE", "LT", "LE", "GT", "GE"):
        right = stack.pop()
        left = stack.pop()
        stack.append(_exec_comparison(op, left, right))
        return pc + 1
    if op == "NEG":
        val = stack.pop()
        if not is_num(val):
            raise VMRuntimeError("Unary '-' requires a number")
        stack.append(-val)  # type: ignore[operator]
        return pc + 1
    if op == "NOT":
        val = stack.pop()
        if type(val) is not bool:
            raise VMRuntimeError("'not' requires a bool")
        stack.append(not val)
        return pc + 1
    if op == "PRINT":
        output.append(_format_print_value(stack.pop()))
        return pc + 1
    if op == "POP":
        stack.pop()
        return pc + 1
    if op == "JUMP":
        return arg  # type: ignore[return-value]
    if op == "JUMP_IF_FALSE":
        cond = stack.pop()
        if type(cond) is not bool:
            raise VMRuntimeError("JUMP_IF_FALSE condition must be a bool")
        return arg if not cond else (pc + 1)  # type: ignore[return-value]
    raise VMRuntimeError(f"Unknown opcode {op}")


def execute(program: Program, *, step_limit: int = 100_000) -> list[str]:
    if type(step_limit) is not int or step_limit <= 0:
        raise ValueError("step_limit must be a positive int")
    slots: list[object] = [_UNSET] * len(program.names)
    stack: list[object] = []
    output: list[str] = []
    pc = 0
    steps = 0
    num_instructions = len(program.instructions)
    while pc < num_instructions:
        steps += 1
        if steps > step_limit:
            raise StepLimitError("Execution exceeded step limit")
        instr = program.instructions[pc]
        if instr.op == "HALT":
            break
        pc = _dispatch_instr(instr.op, instr.arg, stack, slots, program, output, pc)
    return output
