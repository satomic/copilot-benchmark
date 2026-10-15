"""Tree-walking evaluator for minilang."""

import operator

from .builtins import FUNCTIONS, check_arity, type_name
from .errors import EvalError
from .parser import Binary, Call, Literal, Unary, Var, parse

_VALUE_TYPES = (float, str, bool)
_COMPARE = {
    "<": operator.lt,
    "<=": operator.le,
    ">": operator.gt,
    ">=": operator.ge,
}


def evaluate(source, env=None):
    """Parse and evaluate ``source``. ``env`` is read but never mutated."""
    return _eval(parse(source), {} if env is None else env)


def _eval(node, env):
    if isinstance(node, Literal):
        return node.value
    if isinstance(node, Var):
        return _lookup(node, env)
    if isinstance(node, Unary):
        return _unary(node, env)
    if isinstance(node, Binary):
        return _binary(node, env)
    if isinstance(node, Call):
        return _call(node, env)
    raise EvalError(f"internal error: unknown node {node!r}")


def _lookup(node, env):
    if node.name not in env:
        raise EvalError(f"undefined variable: {node.name}", node.position)
    value = env[node.name]
    if type(value) not in _VALUE_TYPES:
        raise EvalError(f"unsupported value for {node.name}: {value!r}", node.position)
    return value


def _require(kind, value, context):
    ok = type(value) is bool if kind == "boolean" else type(value) is float
    if not ok:
        raise EvalError(f"{context} requires a {kind}, got {type_name(value)}")
    return value


def _unary(node, env):
    value = _eval(node.operand, env)
    if node.op == "not":
        return not _require("boolean", value, "'not'")
    return -_require("number", value, "unary '-'")


def _binary(node, env):
    op = node.op
    if op in ("and", "or"):
        return _logical(node, env)
    left = _eval(node.left, env)
    right = _eval(node.right, env)
    if op == "==":
        return _equal(left, right)
    if op == "!=":
        return not _equal(left, right)
    if op in _COMPARE:
        return _ordering(op, left, right)
    if op == "+":
        return _add(left, right)
    if op in ("-", "*", "/", "%", "^"):
        return _arithmetic(node, left, right)
    raise EvalError(f"internal error: unknown operator {op!r}")


def _logical(node, env):
    left = _require("boolean", _eval(node.left, env), f"'{node.op}'")
    if node.op == "and" and not left:
        return False
    if node.op == "or" and left:
        return True
    return _require("boolean", _eval(node.right, env), f"'{node.op}'")


def _equal(a, b):
    return type(a) is type(b) and a == b


def _ordering(op, a, b):
    both_num = type(a) is float and type(b) is float
    both_str = type(a) is str and type(b) is str
    if not (both_num or both_str):
        raise EvalError(f"cannot compare {type_name(a)} with {type_name(b)} using '{op}'")
    return _COMPARE[op](a, b)


def _add(a, b):
    if (type(a) is float and type(b) is float) or (type(a) is str and type(b) is str):
        return a + b
    raise EvalError(f"cannot add {type_name(a)} and {type_name(b)}")


def _arithmetic(node, a, b):
    op = node.op
    if type(a) is not float or type(b) is not float:
        raise EvalError(f"'{op}' requires numbers, got {type_name(a)} and {type_name(b)}")
    if op == "-":
        return a - b
    if op == "*":
        return a * b
    if op == "/":
        if b == 0:
            raise EvalError("division by zero", node.position)
        return a / b
    if op == "%":
        if b == 0:
            raise EvalError("modulo by zero", node.position)
        return a % b
    # "^"
    try:
        result = a ** b
    except ZeroDivisionError:
        raise EvalError("zero cannot be raised to a negative power", node.position)
    except OverflowError:
        raise EvalError("numeric overflow in '^'", node.position)
    if isinstance(result, complex):
        raise EvalError("'^' result is not a real number", node.position)
    return result


def _call(node, env):
    name = node.name
    if name not in FUNCTIONS and name != "if":
        raise EvalError(f"undefined function: {name}", node.position)
    check_arity(name, len(node.args))
    if name == "if":
        cond = _require("boolean", _eval(node.args[0], env), "if() condition")
        return _eval(node.args[1] if cond else node.args[2], env)
    args = [_eval(arg, env) for arg in node.args]
    return FUNCTIONS[name](*args)
