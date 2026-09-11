"""Evaluate a minilang AST."""

from __future__ import annotations

from . import builtins as _builtins
from .errors import EvalError
from .parser import Binary, Call, Literal, Logical, Unary, Var, parse

_ORDERED = frozenset({"<", "<=", ">", ">="})


def evaluate(source: str, env: dict | None = None) -> object:
    """Parse and evaluate `source`. The supplied `env` is never mutated."""
    scope = dict(env) if env else {}
    return _eval(parse(source), scope)


def _eval(node: object, env: dict) -> object:
    if isinstance(node, Literal):
        return node.value
    if isinstance(node, Var):
        if node.name not in env:
            raise EvalError(f"undefined variable: {node.name}", node.position)
        return _check_env_value(node.name, env[node.name], node.position)
    if isinstance(node, Unary):
        return _eval_unary(node, env)
    if isinstance(node, Logical):
        return _eval_logical(node, env)
    if isinstance(node, Binary):
        return _eval_binary(node, env)
    if isinstance(node, Call):
        return _eval_call(node, env)
    raise EvalError(f"cannot evaluate node {node!r}")


def _eval_unary(node: Unary, env: dict) -> object:
    value = _eval(node.operand, env)
    if node.op == "not":
        if not isinstance(value, bool):
            raise EvalError(
                f"'not' expects a boolean, got {_type_name(value)}", node.position
            )
        return not value
    if not _is_number(value):
        raise EvalError(
            f"unary '-' expects a number, got {_type_name(value)}", node.position
        )
    return -value


def _eval_logical(node: Logical, env: dict) -> object:
    left = _eval(node.left, env)
    if not isinstance(left, bool):
        raise EvalError(
            "'" + node.op + f"' expects a boolean, got {_type_name(left)}", node.position
        )
    if node.op == "and" and not left:
        return False
    if node.op == "or" and left:
        return True
    right = _eval(node.right, env)
    if not isinstance(right, bool):
        raise EvalError(
            "'" + node.op + f"' expects a boolean, got {_type_name(right)}", node.position
        )
    return right


def _eval_binary(node: Binary, env: dict) -> object:
    op = node.op
    left = _eval(node.left, env)
    right = _eval(node.right, env)

    if op == "==":
        return _equal(left, right)
    if op == "!=":
        return not _equal(left, right)
    if op in _ORDERED:
        return _compare(op, left, right, node.position)

    if op == "+":
        if _is_number(left) and _is_number(right):
            return left + right
        if isinstance(left, str) and isinstance(right, str):
            return left + right
        raise EvalError(
            "'+' expects two numbers or two strings, got "
            f"{_type_name(left)} and {_type_name(right)}",
            node.position,
        )

    if not (_is_number(left) and _is_number(right)):
        raise EvalError(
            "'" + op + f"' expects numbers, got {_type_name(left)} and {_type_name(right)}",
            node.position,
        )

    if op == "-":
        return left - right
    if op == "*":
        return left * right
    if op == "/":
        if right == 0:
            raise EvalError("division by zero", node.position)
        return left / right
    if op == "%":
        if right == 0:
            raise EvalError("modulo by zero", node.position)
        return left % right
    if op == "^":
        try:
            result = left ** right
        except OverflowError:
            raise EvalError("numeric overflow in '^'", node.position) from None
        if isinstance(result, complex):
            raise EvalError("'^' produced a non-real result", node.position)
        return float(result)

    raise EvalError(f"unknown operator {op!r}", node.position)


def _eval_call(node: Call, env: dict) -> object:
    name = node.name
    if not _builtins.is_builtin(name):
        raise EvalError(f"undefined function: {name}", node.position)

    if name in _builtins.LAZY:
        _builtins.check_arity(name, len(node.args))
        condition = _eval(node.args[0], env)
        if not isinstance(condition, bool):
            raise EvalError(
                f"if() expects a boolean condition, got {_type_name(condition)}",
                node.position,
            )
        branch = node.args[1] if condition else node.args[2]
        return _eval(branch, env)

    args = [_eval(arg, env) for arg in node.args]
    return _builtins.call(name, args)


def _equal(left: object, right: object) -> bool:
    if type(left) is not type(right):
        return False
    return bool(left == right)


def _compare(op: str, left: object, right: object, position: int) -> bool:
    both_numbers = _is_number(left) and _is_number(right)
    both_strings = isinstance(left, str) and isinstance(right, str)
    if not (both_numbers or both_strings):
        raise EvalError(
            "'" + op + "' expects two numbers or two strings, got "
            f"{_type_name(left)} and {_type_name(right)}",
            position,
        )
    if op == "<":
        return left < right
    if op == "<=":
        return left <= right
    if op == ">":
        return left > right
    return left >= right


def _is_number(value: object) -> bool:
    return isinstance(value, float) and not isinstance(value, bool)


def _check_env_value(name: str, value: object, position: int) -> object:
    if isinstance(value, (bool, str)) or _is_number(value):
        return value
    raise EvalError(f"unsupported value for {name}: {value!r}", position)


def _type_name(value: object) -> str:
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    return type(value).__name__
