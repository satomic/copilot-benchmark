"""Evaluator for minilang ASTs."""

import math

from .errors import EvalError
from .parser import (
    AndNode,
    BinOpNode,
    BoolNode,
    CallNode,
    IdentNode,
    NotNode,
    NumberNode,
    OrNode,
    StringNode,
    UnaryMinusNode,
)

_COMPARISON_OPS = ("<", "<=", ">", ">=")


def format_number(x: float) -> str:
    """Format a number the way the REPL displays it (rule 33)."""
    if math.isfinite(x) and x == int(x):
        return str(int(x))
    return repr(x)


def format_string(s: str) -> str:
    """Format a string with surrounding quotes and re-escaped contents."""
    out = ['"']
    for ch in s:
        if ch == "\\":
            out.append("\\\\")
        elif ch == '"':
            out.append('\\"')
        elif ch == "\n":
            out.append("\\n")
        elif ch == "\t":
            out.append("\\t")
        elif ch == "\r":
            out.append("\\r")
        else:
            out.append(ch)
    out.append('"')
    return "".join(out)


def format_value(v) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, float):
        return format_number(v)
    if isinstance(v, str):
        return format_string(v)
    raise TypeError(f"cannot format value: {v!r}")


def _values_equal(a, b) -> bool:
    if type(a) is not type(b):
        return False
    return a == b


def eval_node(node, env: dict):
    if isinstance(node, NumberNode):
        return node.value
    if isinstance(node, StringNode):
        return node.value
    if isinstance(node, BoolNode):
        return node.value

    if isinstance(node, IdentNode):
        if node.name not in env:
            raise EvalError(f"undefined variable: {node.name}")
        val = env[node.name]
        if not isinstance(val, (float, str, bool)):
            raise EvalError(f"unsupported value for {node.name}: {val!r}")
        return val

    if isinstance(node, UnaryMinusNode):
        val = eval_node(node.operand, env)
        if not isinstance(val, float):
            raise EvalError("unary '-' requires a number")
        return -val

    if isinstance(node, NotNode):
        val = eval_node(node.operand, env)
        if not isinstance(val, bool):
            raise EvalError("'not' requires a boolean")
        return not val

    if isinstance(node, AndNode):
        left = eval_node(node.left, env)
        if not isinstance(left, bool):
            raise EvalError("'and' requires boolean operands")
        if left is False:
            return False
        right = eval_node(node.right, env)
        if not isinstance(right, bool):
            raise EvalError("'and' requires boolean operands")
        return right

    if isinstance(node, OrNode):
        left = eval_node(node.left, env)
        if not isinstance(left, bool):
            raise EvalError("'or' requires boolean operands")
        if left is True:
            return True
        right = eval_node(node.right, env)
        if not isinstance(right, bool):
            raise EvalError("'or' requires boolean operands")
        return right

    if isinstance(node, BinOpNode):
        return _eval_binop(node, env)

    if isinstance(node, CallNode):
        return _eval_call(node, env)

    raise EvalError(f"cannot evaluate node: {node!r}")


def _is_number(v) -> bool:
    return isinstance(v, float)


def _eval_binop(node, env):
    op = node.op
    left = eval_node(node.left, env)
    right = eval_node(node.right, env)

    if op == "+":
        if _is_number(left) and _is_number(right):
            return left + right
        if isinstance(left, str) and isinstance(right, str):
            return left + right
        raise EvalError("'+' requires two numbers or two strings")

    if op in ("-", "*", "/", "%"):
        if not (_is_number(left) and _is_number(right)):
            raise EvalError(f"'{op}' requires two numbers")
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
        if not (_is_number(left) and _is_number(right)):
            raise EvalError("'^' requires two numbers")
        try:
            result = left**right
        except OverflowError:
            raise EvalError("result too large")
        except ZeroDivisionError:
            raise EvalError("division by zero")
        except ValueError:
            raise EvalError("result is not a real number")
        if isinstance(result, complex):
            raise EvalError("result is not a real number")
        if isinstance(result, float) and math.isnan(result):
            raise EvalError("result is not a real number")
        return float(result)

    if op == "==" or op == "!=":
        eq = _values_equal(left, right)
        return eq if op == "==" else not eq

    if op in _COMPARISON_OPS:
        if _is_number(left) and _is_number(right):
            pass
        elif isinstance(left, str) and isinstance(right, str):
            pass
        else:
            raise EvalError(f"'{op}' requires two numbers or two strings")
        if op == "<":
            return left < right
        if op == "<=":
            return left <= right
        if op == ">":
            return left > right
        if op == ">=":
            return left >= right

    raise EvalError(f"unknown operator: {op}")


def _eval_call(node, env):
    from .builtins import BUILTINS

    name = node.name

    if name == "if":
        if len(node.args) != 3:
            raise EvalError(f"if() takes 3 argument(s), got {len(node.args)}")
        cond = eval_node(node.args[0], env)
        if not isinstance(cond, bool):
            raise EvalError("if() condition must be a boolean")
        if cond:
            return eval_node(node.args[1], env)
        return eval_node(node.args[2], env)

    if name not in BUILTINS:
        raise EvalError(f"undefined function: {name}")

    args = [eval_node(a, env) for a in node.args]
    return BUILTINS[name](args)


def evaluate_ast(node, env: dict):
    return eval_node(node, env)
