"""Tree-walking evaluator for minilang."""

from .builtins import BUILTINS
from .errors import EvalError
from .parser import Binary, Boolean, Call, Name, Number, String, Unary, parse


def type_name(value):
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    return type(value).__name__


def _is_num(v):
    return isinstance(v, float) and not isinstance(v, bool)


def _check_env_value(name, value):
    if not isinstance(value, (float, str, bool)):
        raise EvalError(f"unsupported value for {name}: {value!r}")
    return value


class _Evaluator:
    def __init__(self, env):
        self.env = env

    def eval(self, node):
        if isinstance(node, (Number, String, Boolean)):
            return node.value
        if isinstance(node, Name):
            if node.name not in self.env:
                raise EvalError(f"undefined variable: {node.name}", node.position)
            return _check_env_value(node.name, self.env[node.name])
        if isinstance(node, Unary):
            return self.eval_unary(node)
        if isinstance(node, Binary):
            return self.eval_binary(node)
        if isinstance(node, Call):
            fn = BUILTINS.get(node.name)
            if fn is None:
                raise EvalError(f"undefined function: {node.name}", node.position)
            # Builtins receive thunks so that lazy ones (if) evaluate only what they need.
            thunks = [(lambda a=a: self.eval(a)) for a in node.args]
            return fn(thunks)
        raise TypeError(f"unknown node: {node!r}")

    def eval_unary(self, node):
        value = self.eval(node.operand)
        if node.op == "not":
            if not isinstance(value, bool):
                raise EvalError(f"'not' requires a boolean, got {type_name(value)}", node.position)
            return not value
        if not _is_num(value):
            raise EvalError(f"unary '-' requires a number, got {type_name(value)}", node.position)
        return -value

    def eval_binary(self, node):
        op = node.op
        if op in ("and", "or"):
            left = self.eval(node.left)
            if not isinstance(left, bool):
                raise EvalError(f"'{op}' requires booleans, got {type_name(left)}", node.position)
            if (op == "and" and not left) or (op == "or" and left):
                return left
            right = self.eval(node.right)
            if not isinstance(right, bool):
                raise EvalError(f"'{op}' requires booleans, got {type_name(right)}", node.position)
            return right

        left = self.eval(node.left)
        right = self.eval(node.right)

        if op in ("==", "!="):
            equal = type_name(left) == type_name(right) and left == right
            return equal if op == "==" else not equal

        if op in ("<", "<=", ">", ">="):
            if not ((_is_num(left) and _is_num(right))
                    or (isinstance(left, str) and isinstance(right, str))):
                raise EvalError(
                    f"cannot compare {type_name(left)} and {type_name(right)} with '{op}'",
                    node.position,
                )
            if op == "<":
                return left < right
            if op == "<=":
                return left <= right
            if op == ">":
                return left > right
            return left >= right

        if op == "+":
            if _is_num(left) and _is_num(right):
                return left + right
            if isinstance(left, str) and isinstance(right, str):
                return left + right
            raise EvalError(
                f"cannot add {type_name(left)} and {type_name(right)}", node.position
            )

        if not (_is_num(left) and _is_num(right)):
            raise EvalError(
                f"'{op}' requires numbers, got {type_name(left)} and {type_name(right)}",
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
            except ZeroDivisionError:
                raise EvalError("zero cannot be raised to a negative power", node.position) from None
            except OverflowError:
                raise EvalError("numeric overflow in '^'", node.position) from None
            if not isinstance(result, float):
                raise EvalError("'^' result is not a real number", node.position)
            return result
        raise TypeError(f"unknown operator: {op}")


def evaluate(source: str, env: dict | None = None) -> object:
    tree = parse(source)
    # Work on a private copy so the caller's mapping is never mutated.
    scope = dict(env) if env is not None else {}
    try:
        return _Evaluator(scope).eval(tree)
    except RecursionError:
        raise EvalError("expression too deeply nested") from None
