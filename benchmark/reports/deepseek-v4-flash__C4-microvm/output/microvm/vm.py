from microvm.errors import VMRuntimeError, StepLimitError
from microvm.compiler import Program


def _check_num(val: object, context: str = "") -> None:
    if isinstance(val, bool):
        raise VMRuntimeError(f"Type error: BOOL not allowed in {context}")


def _fmt_bool(val: bool) -> str:
    return "true" if val else "false"


def _eq_impl(l: object, r: object) -> bool:
    if isinstance(l, bool) and isinstance(r, bool):
        return l == r
    if isinstance(l, bool) or isinstance(r, bool):
        return False
    if isinstance(l, str) and isinstance(r, str):
        return l == r
    if isinstance(l, (int, float)) and isinstance(r, (int, float)):
        return l == r  # type: ignore
    return False


def _cmp_impl(l: object, r: object, op: str) -> bool:
    if isinstance(l, bool) or isinstance(r, bool):
        raise VMRuntimeError("Type error: comparison on BOOL")
    if isinstance(l, str) and isinstance(r, str):
        if op == "<":
            return l < r
        elif op == "<=":
            return l <= r
        elif op == ">":
            return l > r
        elif op == ">=":
            return l >= r
    if isinstance(l, (int, float)) and isinstance(r, (int, float)):
        if op == "<":
            return l < r  # type: ignore
        elif op == "<=":
            return l <= r  # type: ignore
        elif op == ">":
            return l > r  # type: ignore
        elif op == ">=":
            return l >= r  # type: ignore
    raise VMRuntimeError(f"Type error: cannot compare {type(l).__name__} with {type(r).__name__}")


def _exec_op_arith(op: str, l: object, r: object) -> object:
    if op == "ADD":
        if isinstance(l, str) and isinstance(r, str):
            return l + r
        if isinstance(l, bool) or isinstance(r, bool):
            raise VMRuntimeError("Type error: + on BOOL")
        if isinstance(l, str) or isinstance(r, str):
            raise VMRuntimeError("Type error: + requires both numbers or both strings")
        return l + r  # type: ignore
    if op in ("SUB", "MUL"):
        _check_num(l, op)
        _check_num(r, op)
        if op == "SUB":
            return l - r  # type: ignore
        return l * r  # type: ignore
    if op == "DIV":
        _check_num(l, "DIV")
        _check_num(r, "DIV")
        if r == 0:
            raise VMRuntimeError("Division by zero")
        return l / r  # type: ignore
    if op == "MOD":
        _check_num(l, "MOD")
        _check_num(r, "MOD")
        if not isinstance(l, int) or not isinstance(r, int):
            raise VMRuntimeError("Type error: % requires INT operands")
        if r == 0:
            raise VMRuntimeError("Modulo by zero")
        return l % r
    raise AssertionError(f"Unknown arith op: {op}")


def _exec_op_compare(op: str, l: object, r: object) -> object:
    if op == "EQ":
        return _eq_impl(l, r)
    if op == "NE":
        return not _eq_impl(l, r)
    if op == "LT":
        return _cmp_impl(l, r, "<")
    if op == "LE":
        return _cmp_impl(l, r, "<=")
    if op == "GT":
        return _cmp_impl(l, r, ">")
    if op == "GE":
        return _cmp_impl(l, r, ">=")
    raise AssertionError(f"Unknown cmp op: {op}")


def _exec_instr(op: str, arg: int | None, ctx: dict) -> bool:
    stack = ctx["stack"]
    slots = ctx["slots"]
    constants = ctx["constants"]
    names = ctx["names"]
    output = ctx["output"]

    if op == "HALT":
        return False
    elif op == "CONST":
        stack.append(constants[arg])  # type: ignore
    elif op == "LOAD":
        init, val = slots[arg]  # type: ignore
        if not init:
            raise VMRuntimeError(f"Variable '{names[arg]}' declared but never assigned")
        stack.append(val)
    elif op == "STORE":
        slots[arg] = (True, stack.pop())  # type: ignore
    elif op in ("ADD", "SUB", "MUL", "DIV", "MOD"):
        r = stack.pop()
        l = stack.pop()
        stack.append(_exec_op_arith(op, l, r))
    elif op == "NEG":
        v = stack.pop()
        _check_num(v, "NEG")
        stack.append(-v)  # type: ignore
    elif op == "NOT":
        v = stack.pop()
        if not isinstance(v, bool):
            raise VMRuntimeError("Type error: NOT requires BOOL")
        stack.append(not v)
    elif op in ("EQ", "NE", "LT", "LE", "GT", "GE"):
        r = stack.pop()
        l = stack.pop()
        stack.append(_exec_op_compare(op, l, r))
    elif op == "JUMP":
        ctx["ip"] = arg  # type: ignore
        return True
    elif op == "JUMP_IF_FALSE":
        cond = stack.pop()
        if not isinstance(cond, bool):
            raise VMRuntimeError("Type error: condition must be BOOL")
        if not cond:
            ctx["ip"] = arg  # type: ignore
            return True
    elif op == "PRINT":
        val = stack.pop()
        if isinstance(val, bool):
            output.append(_fmt_bool(val))
        elif isinstance(val, float):
            output.append(str(val))
        else:
            output.append(str(val))
    elif op == "POP":
        stack.pop()
    ctx["ip"] += 1
    return True


def execute(program: Program, *, step_limit: int = 100_000) -> list[str]:
    if isinstance(step_limit, bool) or not isinstance(step_limit, int):
        raise ValueError("step_limit must be a positive int")
    if step_limit <= 0:
        raise ValueError("step_limit must be a positive int")

    instrs = program.instructions
    ctx = {
        "constants": program.constants,
        "names": program.names,
        "slots": [(False, None) for _ in program.names],
        "stack": [],
        "ip": 0,
        "output": [],
    }
    steps = 0

    while ctx["ip"] < len(instrs):
        steps += 1
        if steps > step_limit:
            raise StepLimitError(f"Step limit {step_limit} exceeded")
        instr = instrs[ctx["ip"]]
        if not _exec_instr(instr.op, instr.arg, ctx):
            break

    return ctx["output"]