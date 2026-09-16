import math
from .errors import EvalError
from .parser import Literal, Variable, Unary, Binary, Call, parse
from .builtins import call_builtin, BUILTIN_NAMES


def _value(name, value):
    if type(value) not in (float, str, bool):
        raise EvalError(f"unsupported value for {name}: {value!r}")
    return value


def evaluate(source, env=None):
    return Evaluator(dict(env or {})).visit(parse(source))


class Evaluator:
    def __init__(self, env):
        self.env = env

    def visit(self, node):
        if isinstance(node, Literal): return node.value
        if isinstance(node, Variable):
            if node.name not in self.env: raise EvalError(f"undefined variable: {node.name}")
            return _value(node.name, self.env[node.name])
        if isinstance(node, Unary):
            value = self.visit(node.operand)
            if node.op == "not":
                if type(value) is not bool: raise EvalError("not requires a boolean")
                return not value
            if type(value) is not float: raise EvalError("unary minus requires a number")
            return -value
        if isinstance(node, Binary):
            if node.op in ("and", "or"):
                left = self.visit(node.left)
                if type(left) is not bool: raise EvalError(f"{node.op} requires booleans")
                if node.op == "and" and not left: return False
                if node.op == "or" and left: return True
                right = self.visit(node.right)
                if type(right) is not bool: raise EvalError(f"{node.op} requires booleans")
                return right
            left, right = self.visit(node.left), self.visit(node.right)
            return self.binary(node.op, left, right)
        if isinstance(node, Call):
            if node.name == "if":
                if len(node.args) != 3: raise EvalError(f"if() takes 3 argument(s), got {len(node.args)}")
                cond = self.visit(node.args[0])
                if type(cond) is not bool: raise EvalError("if() condition requires a boolean")
                return self.visit(node.args[1] if cond else node.args[2])
            if node.name not in BUILTIN_NAMES:
                raise EvalError(f"undefined function: {node.name}")
            try: args = [self.visit(arg) for arg in node.args]
            except EvalError: raise
            return call_builtin(node.name, args)
        raise EvalError("invalid expression")

    def binary(self, op, a, b):
        if op == "==": return type(a) is type(b) and a == b
        if op == "!=": return not (type(a) is type(b) and a == b)
        if op in ("+", "-", "*", "/", "%", "^"):
            if op == "+" and type(a) is type(b) and type(a) in (float, str): return a + b
            if op != "+" and type(a) is type(b) is float:
                if op in ("/", "%") and b == 0: raise EvalError("division by zero" if op == "/" else "modulo by zero")
                try:
                    result = { "-": lambda: a-b, "*": lambda: a*b, "/": lambda: a/b,
                               "%": lambda: a % b, "^": lambda: a**b}[op]()
                except (ValueError, OverflowError, ZeroDivisionError):
                    raise EvalError("numeric operation failed")
                if type(result) is complex or not math.isfinite(result): raise EvalError("numeric operation failed")
                return float(result)
            raise EvalError(f"operator {op} requires compatible operands")
        if op in ("<", "<=", ">", ">="):
            if type(a) is not type(b) or type(a) not in (float, str):
                raise EvalError(f"operator {op} requires two numbers or two strings")
            return {"<": a < b, "<=": a <= b, ">": a > b, ">=": a >= b}[op]
        raise EvalError(f"unknown operator: {op}")
