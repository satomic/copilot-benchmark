from .compiler import Program
from .errors import VMRuntimeError, StepLimitError


def _number(x: object) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def _binary(op: str, a: object, b: object) -> object:
    if op in ("ADD", "SUB", "MUL"):
        if op == "ADD" and isinstance(a, str) and isinstance(b, str): return a + b
        if not (_number(a) and _number(b)): raise VMRuntimeError("numeric operands required")
        return {"ADD": a+b, "SUB": a-b, "MUL": a*b}[op]
    if op == "DIV":
        if not (_number(a) and _number(b)) or b == 0: raise VMRuntimeError("invalid division")
        return float(a) / float(b)
    if op == "MOD":
        if type(a) is not int or type(b) is not int or b == 0: raise VMRuntimeError("invalid modulo")
        return a % b
    if op in ("EQ", "NE"):
        eq = (type(a) is type(b) and a == b) or (_number(a) and _number(b) and a == b)
        return eq if op == "EQ" else not eq
    if op in ("LT", "LE", "GT", "GE"):
        if not ((_number(a) and _number(b)) or (isinstance(a, str) and isinstance(b, str))): raise VMRuntimeError("invalid comparison")
        return {"LT": a < b, "LE": a <= b, "GT": a > b, "GE": a >= b}[op]
    raise VMRuntimeError("unknown operation")


def execute(program: Program, *, step_limit: int = 100_000) -> list[str]:
    if isinstance(step_limit, bool) or not isinstance(step_limit, int) or step_limit <= 0: raise ValueError("step_limit must be positive")
    stack: list[object] = []; slots = [None] * len(program.names); assigned = [False] * len(slots); output: list[str] = []
    ip = steps = 0
    while ip < len(program.instructions):
        steps += 1
        if steps > step_limit: raise StepLimitError("step limit exceeded")
        ins = program.instructions[ip]; op = ins.op
        if op == "CONST": stack.append(program.constants[ins.arg]); ip += 1
        elif op == "LOAD":
            if not assigned[ins.arg]: raise VMRuntimeError("variable " + program.names[ins.arg] + " is unassigned")
            stack.append(slots[ins.arg]); ip += 1
        elif op == "STORE": slots[ins.arg] = stack.pop(); assigned[ins.arg] = True; ip += 1
        elif op == "JUMP": ip = ins.arg
        elif op == "JUMP_IF_FALSE":
            x = stack.pop()
            if not isinstance(x, bool): raise VMRuntimeError("condition must be bool")
            ip = ins.arg if not x else ip + 1
        elif op == "PRINT":
            x = stack.pop(); output.append("true" if x is True else "false" if x is False else str(x)); ip += 1
        elif op == "NEG":
            x = stack.pop()
            if not _number(x): raise VMRuntimeError("numeric operand required")
            stack.append(-x); ip += 1
        elif op == "NOT":
            x = stack.pop()
            if not isinstance(x, bool): raise VMRuntimeError("bool operand required")
            stack.append(not x); ip += 1
        elif op == "POP": stack.pop(); ip += 1
        elif op == "HALT": return output
        else:
            b, a = stack.pop(), stack.pop(); stack.append(_binary(op, a, b)); ip += 1
    raise VMRuntimeError("program has no halt")
