from .builtins import BUILTINS, LAZY_BUILTINS
from .errors import EvalError
from .parser import Binary, Boolean, Call, Number, String, Unary, Variable, parse


def _is_num(v):
    return isinstance(v, float)


def _require_bool(v, what):
    if not isinstance(v, bool):
        raise EvalError(f"{what} requires a boolean")
    return v


def _equal(a, b):
    if type(a) is not type(b):
        return False
    return a == b


def _binary(op, a, b):
    if op == "+":
        if _is_num(a) and _is_num(b):
            return a + b
        if isinstance(a, str) and isinstance(b, str):
            return a + b
        raise EvalError("operator + requires two numbers or two strings")
    if op in ("-", "*", "/", "%", "^"):
        if not (_is_num(a) and _is_num(b)):
            raise EvalError(f"operator {op} requires numbers")
        if op == "-":
            return a - b
        if op == "*":
            return a * b
        if op == "/":
            if b == 0:
                raise EvalError("division by zero")
            return a / b
        if op == "%":
            if b == 0:
                raise EvalError("modulo by zero")
            return a % b
        try:
            r = a ** b
        except (ZeroDivisionError, OverflowError):
            raise EvalError("invalid power")
        if not isinstance(r, float):
            raise EvalError("power result is not a real number")
        return r
    if op == "==":
        return _equal(a, b)
    if op == "!=":
        return not _equal(a, b)
    if (_is_num(a) and _is_num(b)) or (isinstance(a, str) and isinstance(b, str)):
        if op == "<":
            return a < b
        if op == "<=":
            return a <= b
        if op == ">":
            return a > b
        return a >= b
    raise EvalError(f"operator {op} requires two numbers or two strings")


def _eval(node, env):
    if isinstance(node, (Number, String, Boolean)):
        return node.value
    if isinstance(node, Variable):
        if node.name not in env:
            raise EvalError(f"undefined variable: {node.name}")
        v = env[node.name]
        if not isinstance(v, (float, str, bool)):
            raise EvalError(f"unsupported value for {node.name}: {v!r}")
        return v
    if isinstance(node, Unary):
        v = _eval(node.operand, env)
        if node.op == "not":
            return not _require_bool(v, "not")
        if not _is_num(v):
            raise EvalError("unary - requires a number")
        return -v
    if isinstance(node, Binary):
        if node.op in ("and", "or"):
            left = _require_bool(_eval(node.left, env), node.op)
            if node.op == "and" and not left:
                return False
            if node.op == "or" and left:
                return True
            return _require_bool(_eval(node.right, env), node.op)
        return _binary(node.op, _eval(node.left, env), _eval(node.right, env))
    if isinstance(node, Call):
        if node.name in LAZY_BUILTINS:
            if len(node.args) != 3:
                raise EvalError(f"if() takes 3 argument(s), got {len(node.args)}")
            cond = _require_bool(_eval(node.args[0], env), "if condition")
            return _eval(node.args[1 if cond else 2], env)
        fn = BUILTINS.get(node.name)
        if fn is None:
            raise EvalError(f"undefined function: {node.name}")
        return fn(*[_eval(a, env) for a in node.args])
    raise EvalError(f"unknown node: {node!r}")


def evaluate(source, env=None):
    tree = parse(source)
    return _eval(tree, {} if env is None else env)
