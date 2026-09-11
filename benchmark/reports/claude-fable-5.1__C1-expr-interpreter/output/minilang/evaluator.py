"""Tree-walking evaluator for minilang."""

import math

from .builtins import BUILTINS, LAZY_BUILTINS, type_name
from .errors import EvalError
from .parser import (
    Binary,
    Boolean,
    Call,
    Node,
    Number,
    String,
    Unary,
    Variable,
    parse,
)


def _is_number(value: object) -> bool:
    return type(value) is float


def _is_bool(value: object) -> bool:
    return type(value) is bool


def _require_numbers(op: str, left: object, right: object, position: int) -> None:
    if not (_is_number(left) and _is_number(right)):
        raise EvalError(
            f"unsupported operand types for '{op}': {type_name(left)} and {type_name(right)}",
            position,
        )


class _Evaluator:
    def __init__(self, env: dict):
        self.env = env

    def eval(self, node: Node) -> object:
        method = getattr(self, f"_eval_{type(node).__name__}")
        return method(node)

    def _eval_Number(self, node: Number) -> float:
        return node.value

    def _eval_String(self, node: String) -> str:
        return node.value

    def _eval_Boolean(self, node: Boolean) -> bool:
        return node.value

    def _eval_Variable(self, node: Variable) -> object:
        if node.name not in self.env:
            raise EvalError(f"undefined variable: {node.name}", node.position)
        value = self.env[node.name]
        # bool is checked by exact type so int/bool confusion cannot slip through.
        if type(value) not in (float, str, bool):
            raise EvalError(
                f"unsupported value for {node.name}: {value!r}", node.position
            )
        return value

    def _eval_Call(self, node: Call) -> object:
        if node.name in LAZY_BUILTINS:
            return LAZY_BUILTINS[node.name](node.args, self.eval)
        if node.name in BUILTINS:
            args = [self.eval(arg) for arg in node.args]
            return BUILTINS[node.name](args)
        raise EvalError(f"undefined function: {node.name}", node.position)

    def _eval_Unary(self, node: Unary) -> object:
        value = self.eval(node.operand)
        if node.op == "-":
            if not _is_number(value):
                raise EvalError(
                    f"unary '-' requires a number, got {type_name(value)}", node.position
                )
            return -value
        if node.op == "not":
            if not _is_bool(value):
                raise EvalError(
                    f"'not' requires a boolean, got {type_name(value)}", node.position
                )
            return not value
        raise EvalError(f"unknown unary operator {node.op!r}", node.position)

    def _eval_Binary(self, node: Binary) -> object:
        op = node.op
        if op in ("and", "or"):
            left = self.eval(node.left)
            if not _is_bool(left):
                raise EvalError(
                    f"'{op}' requires booleans, got {type_name(left)}", node.position
                )
            if op == "and" and not left:
                return False
            if op == "or" and left:
                return True
            right = self.eval(node.right)
            if not _is_bool(right):
                raise EvalError(
                    f"'{op}' requires booleans, got {type_name(right)}", node.position
                )
            return right

        left = self.eval(node.left)
        right = self.eval(node.right)
        pos = node.position

        if op == "==":
            return type(left) is type(right) and left == right
        if op == "!=":
            return not (type(left) is type(right) and left == right)
        if op in ("<", "<=", ">", ">="):
            same_numbers = _is_number(left) and _is_number(right)
            same_strings = type(left) is str and type(right) is str
            if not (same_numbers or same_strings):
                raise EvalError(
                    f"cannot compare {type_name(left)} and {type_name(right)} with '{op}'",
                    pos,
                )
            if op == "<":
                return left < right
            if op == "<=":
                return left <= right
            if op == ">":
                return left > right
            return left >= right
        if op == "+":
            if _is_number(left) and _is_number(right):
                return left + right
            if type(left) is str and type(right) is str:
                return left + right
            raise EvalError(
                f"unsupported operand types for '+': {type_name(left)} and {type_name(right)}",
                pos,
            )
        if op == "-":
            _require_numbers(op, left, right, pos)
            return left - right
        if op == "*":
            _require_numbers(op, left, right, pos)
            return left * right
        if op == "/":
            _require_numbers(op, left, right, pos)
            if right == 0:
                raise EvalError("division by zero", pos)
            return left / right
        if op == "%":
            _require_numbers(op, left, right, pos)
            if right == 0:
                raise EvalError("modulo by zero", pos)
            return left % right
        if op == "^":
            _require_numbers(op, left, right, pos)
            try:
                result = left ** right
            except ZeroDivisionError:
                raise EvalError("zero cannot be raised to a negative power", pos) from None
            except OverflowError:
                raise EvalError("result of '^' is too large", pos) from None
            if not isinstance(result, float) or math.isnan(result):
                raise EvalError("result of '^' is not a real number", pos)
            return result
        raise EvalError(f"unknown operator {op!r}", pos)


def evaluate(source: str, env: "dict | None" = None) -> object:
    """Parse and evaluate ``source``. ``env`` is read but never mutated."""
    tree = parse(source)
    return evaluate_node(tree, env)


def evaluate_node(tree: Node, env: "dict | None" = None) -> object:
    return _Evaluator(env if env is not None else {}).eval(tree)
