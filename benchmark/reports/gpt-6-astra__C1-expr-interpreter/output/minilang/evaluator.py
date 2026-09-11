import operator

from .builtins import (
    Value,
    call_builtin,
    get_builtin,
    require_boolean,
    require_number,
)
from .errors import EvalError
from .parser import Binary, Call, Literal, Node, Unary, Variable, parse


_ARITHMETIC = {
    "+": operator.add,
    "-": operator.sub,
    "*": operator.mul,
    "/": operator.truediv,
    "%": operator.mod,
    "^": operator.pow,
}
_ORDERING = {
    "<": operator.lt,
    "<=": operator.le,
    ">": operator.gt,
    ">=": operator.ge,
}


def _evaluate(node: Node, env: dict) -> Value:
    if isinstance(node, Literal):
        return node.value
    if isinstance(node, Variable):
        if node.name not in env:
            raise EvalError(f"undefined variable: {node.name}")
        value = env[node.name]
        if type(value) not in (float, str, bool):
            raise EvalError(f"unsupported value for {node.name}: {value!r}")
        return value
    if isinstance(node, Call):
        builtin = get_builtin(node.name, len(node.arguments))
        if node.name == "if":
            condition = require_boolean(_evaluate(node.arguments[0], env))
            return _evaluate(node.arguments[1 if condition else 2], env)
        return call_builtin(builtin, [_evaluate(arg, env) for arg in node.arguments])
    if isinstance(node, Unary):
        value = _evaluate(node.operand, env)
        if node.operator == "not":
            return not require_boolean(value)
        return -require_number(value)
    assert isinstance(node, Binary)
    left = _evaluate(node.left, env)
    op = node.operator
    if op in {"and", "or"}:
        condition = require_boolean(left)
        if (op == "and" and not condition) or (op == "or" and condition):
            return condition
        return require_boolean(_evaluate(node.right, env))
    right = _evaluate(node.right, env)
    if op in {"==", "!="}:
        equal = type(left) is type(right) and left == right
        return equal if op == "==" else not equal
    if op in _ORDERING:
        if type(left) is not type(right) or type(left) not in (float, str):
            raise EvalError("comparison requires two numbers or two strings")
        return _ORDERING[op](left, right)
    if op == "+" and type(left) is str and type(right) is str:
        return left + right
    a, b = require_number(left), require_number(right)
    if op == "/" and b == 0:
        raise EvalError("division by zero")
    if op == "%" and b == 0:
        raise EvalError("modulo by zero")
    try:
        result = _ARITHMETIC[op](a, b)
    except (ZeroDivisionError, OverflowError, ValueError) as error:
        raise EvalError(str(error)) from error
    if type(result) is not float:
        raise EvalError("result is not a real number")
    return result


def evaluate(source: str, env: dict | None = None) -> Value:
    return _evaluate(parse(source), {} if env is None else env)
