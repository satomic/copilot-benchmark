"""Evaluator for minilang expressions."""

import math

from minilang.builtins import call_builtin
from minilang.errors import EvalError
from minilang.parser import BinaryOp, BoolLit, Call, Name, Number, StringLit, UnaryOp, parse


def evaluate(source: str, env: dict | None = None):
    """Evaluate ``source``. ``env`` is read but never mutated."""
    if env is None:
        env = {}
    return _eval(parse(source), env)


def _eval(node, env: dict):
    if isinstance(node, Number):
        return node.value
    if isinstance(node, StringLit):
        return node.value
    if isinstance(node, BoolLit):
        return node.value
    if isinstance(node, Name):
        return _eval_name(node, env)
    if isinstance(node, UnaryOp):
        return _eval_unary(node, env)
    if isinstance(node, BinaryOp):
        return _eval_binary(node, env)
    if isinstance(node, Call):
        return _eval_call(node, env)
    raise EvalError("unknown expression", getattr(node, "position", None))


def _eval_name(node: Name, env: dict):
    if node.name not in env:
        raise EvalError(f"undefined variable: {node.name}", node.position)
    value = env[node.name]
    # bool is a subclass of int; only the three language types are accepted.
    if type(value) not in (float, str, bool):
        raise EvalError(
            f"unsupported value for {node.name}: {value!r}", node.position
        )
    return value


def _eval_unary(node: UnaryOp, env: dict):
    value = _eval(node.operand, env)
    if node.op == "not":
        if type(value) is not bool:
            raise EvalError("not requires a boolean", node.position)
        return not value
    if node.op == "-":
        if type(value) is not float:
            raise EvalError("unary - requires a number", node.position)
        return -value
    raise EvalError(f"unknown operator {node.op}", node.position)


def _eval_binary(node: BinaryOp, env: dict):
    if node.op == "and":
        return _eval_and(node, env)
    if node.op == "or":
        return _eval_or(node, env)
    left = _eval(node.left, env)
    right = _eval(node.right, env)
    return _apply_binary(node.op, left, right, node.position)


def _require_bool(value, position: int | None) -> bool:
    if type(value) is not bool:
        raise EvalError("and/or requires booleans", position)
    return value


def _eval_and(node: BinaryOp, env: dict):
    left = _require_bool(_eval(node.left, env), node.position)
    if not left:
        return False
    return _require_bool(_eval(node.right, env), node.position)


def _eval_or(node: BinaryOp, env: dict):
    left = _require_bool(_eval(node.left, env), node.position)
    if left:
        return True
    return _require_bool(_eval(node.right, env), node.position)


def _apply_binary(op: str, left, right, position: int | None):
    if op == "+":
        if type(left) is float and type(right) is float:
            return left + right
        if type(left) is str and type(right) is str:
            return left + right
        raise EvalError("+ requires two numbers or two strings", position)
    if op in "-*/%^":
        if type(left) is not float or type(right) is not float:
            raise EvalError(f"{op} requires numbers", position)
        if op == "-":
            return left - right
        if op == "*":
            return left * right
        if op == "/":
            if right == 0.0:
                raise EvalError("division by zero", position)
            return left / right
        if op == "%":
            if right == 0.0:
                raise EvalError("modulo by zero", position)
            return left % right
        return _power(left, right, position)
    if op in ("==", "!="):
        equal = type(left) is type(right) and left == right
        return equal if op == "==" else not equal
    if op in ("<", "<=", ">", ">="):
        if not (
            (type(left) is float and type(right) is float)
            or (type(left) is str and type(right) is str)
        ):
            raise EvalError(f"{op} requires two numbers or two strings", position)
        if op == "<":
            return left < right
        if op == "<=":
            return left <= right
        if op == ">":
            return left > right
        return left >= right
    raise EvalError(f"unknown operator {op}", position)


def _power(left: float, right: float, position: int | None) -> float:
    # Complex or non-finite results are not real numbers, e.g. (-8) ^ 0.5.
    try:
        result = left ** right
    except (OverflowError, ZeroDivisionError, ValueError):
        raise EvalError("not a real number", position) from None
    if isinstance(result, complex) or type(result) not in (float, int):
        raise EvalError("not a real number", position)
    result = float(result)
    if not math.isfinite(result):
        raise EvalError("not a real number", position)
    return result


def _eval_call(node: Call, env: dict):
    # ``if`` is lazy: only the taken branch is evaluated. It is not a variable.
    if node.name == "if":
        if len(node.args) != 3:
            raise EvalError(
                f"if() takes 3 argument(s), got {len(node.args)}", node.position
            )
        condition = _eval(node.args[0], env)
        if type(condition) is not bool:
            raise EvalError("if() condition must be a boolean", node.position)
        chosen = node.args[1] if condition else node.args[2]
        return _eval(chosen, env)
    if node.name not in {
        "abs",
        "min",
        "max",
        "round",
        "len",
        "upper",
        "lower",
        "str",
        "num",
    }:
        raise EvalError(f"undefined function: {node.name}", node.position)
    args = [_eval(arg, env) for arg in node.args]
    try:
        return call_builtin(node.name, args)
    except EvalError as exc:
        if exc.position is None:
            exc.position = node.position
        raise
