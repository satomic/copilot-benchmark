"""Evaluator: walks the AST and produces minilang values."""

import math

from .builtins import (
    BUILTINS,
    BUILTIN_NAMES,
    LAZY_BUILTINS,
    check_if_arity,
    check_if_condition,
    is_boolean,
    is_number,
    is_string,
    is_value,
)
from .errors import EvalError
from .parser import BinaryOp, Call, Literal, LogicalOp, UnaryOp, Variable, parse

_ORDER_OPS = frozenset({"<", "<=", ">", ">="})


def _type_name(value):
    if is_boolean(value):
        return "boolean"
    if is_number(value):
        return "number"
    if is_string(value):
        return "string"
    return type(value).__name__


def _require_number(value, context):
    if not is_number(value):
        raise EvalError(f"{context} requires numbers, got {_type_name(value)}")
    return value


def _lookup(env, name):
    if name not in env:
        raise EvalError(f"undefined variable: {name}")
    value = env[name]
    if not is_value(value):
        # Rule 26: env values are validated lazily, when the name is read.
        raise EvalError(f"unsupported value for {name}: {value!r}")
    return value


def _eval_arithmetic(op, left, right):
    if op == "+":
        if is_number(left) and is_number(right):
            return left + right
        if is_string(left) and is_string(right):
            return left + right
        raise EvalError(
            "'+' requires two numbers or two strings, got "
            f"{_type_name(left)} and {_type_name(right)}"
        )

    _require_number(left, f"'{op}'")
    _require_number(right, f"'{op}'")

    if op == "-":
        return left - right
    if op == "*":
        return left * right
    if op == "/":
        if right == 0:
            raise EvalError("division by zero")
        return left / right
    if op == "%":
        if right == 0:
            raise EvalError("modulo by zero")
        return left % right
    if op == "^":
        try:
            result = left**right
        except ZeroDivisionError:
            raise EvalError("division by zero") from None
        except (OverflowError, ValueError):
            raise EvalError("'^' produced a result that is not a real number") from None
        if isinstance(result, complex) or (
            isinstance(result, float) and math.isnan(result) and not _nan_input(left, right)
        ):
            raise EvalError("'^' produced a result that is not a real number")
        return float(result)
    raise EvalError(f"unknown operator: {op}")  # pragma: no cover - defensive


def _nan_input(left, right):
    return math.isnan(left) or math.isnan(right)


def _eval_comparison(op, left, right):
    if op == "==":
        return _values_equal(left, right)
    if op == "!=":
        return not _values_equal(left, right)

    both_numbers = is_number(left) and is_number(right)
    both_strings = is_string(left) and is_string(right)
    if not (both_numbers or both_strings):
        raise EvalError(
            f"'{op}' requires two numbers or two strings, got "
            f"{_type_name(left)} and {_type_name(right)}"
        )
    if op == "<":
        return left < right
    if op == "<=":
        return left <= right
    if op == ">":
        return left > right
    return left >= right


def _values_equal(left, right):
    # Rule 19: different types are never equal, so `true == 1` is false
    # (Python would say True).
    if type(left) is not type(right):
        return False
    return left == right


class _Evaluator:
    def __init__(self, env):
        self.env = env

    def eval(self, node):
        if isinstance(node, Literal):
            return node.value
        if isinstance(node, Variable):
            return _lookup(self.env, node.name)
        if isinstance(node, UnaryOp):
            return self._eval_unary(node)
        if isinstance(node, BinaryOp):
            return self._eval_binary(node)
        if isinstance(node, LogicalOp):
            return self._eval_logical(node)
        if isinstance(node, Call):
            return self._eval_call(node)
        raise EvalError(f"cannot evaluate node: {node!r}")  # pragma: no cover

    def _eval_unary(self, node):
        value = self.eval(node.operand)
        if node.op == "-":
            if not is_number(value):
                raise EvalError(f"unary '-' requires a number, got {_type_name(value)}")
            return -value
        if not is_boolean(value):
            raise EvalError(f"'not' requires a boolean, got {_type_name(value)}")
        return not value

    def _eval_binary(self, node):
        left = self.eval(node.left)
        right = self.eval(node.right)
        if node.op in _ORDER_OPS or node.op in ("==", "!="):
            return _eval_comparison(node.op, left, right)
        return _eval_arithmetic(node.op, left, right)

    def _eval_logical(self, node):
        left = self.eval(node.left)
        if not is_boolean(left):
            raise EvalError(
                f"'{node.op}' requires booleans, got {_type_name(left)}"
            )
        if node.op == "and" and left is False:
            return False
        if node.op == "or" and left is True:
            return True
        right = self.eval(node.right)
        if not is_boolean(right):
            raise EvalError(
                f"'{node.op}' requires booleans, got {_type_name(right)}"
            )
        return right

    def _eval_call(self, node):
        name = node.name
        if name not in BUILTIN_NAMES:
            # Rule 25: function names never fall back to variables.
            raise EvalError(f"undefined function: {name}")
        if name in LAZY_BUILTINS:
            check_if_arity(len(node.args))
            condition = check_if_condition(self.eval(node.args[0]))
            return self.eval(node.args[1] if condition else node.args[2])
        args = [self.eval(arg) for arg in node.args]
        return BUILTINS[name](args)


def evaluate_node(node, env=None):
    """Evaluate an already-parsed AST ``node`` in ``env``."""
    # Rule 31: never mutate the caller's mapping.
    local_env = dict(env) if env else {}
    return _Evaluator(local_env).eval(node)


def evaluate(source, env=None):
    """Parse and evaluate ``source``, returning a ``float``, ``str`` or ``bool``."""
    return evaluate_node(parse(source), env)
