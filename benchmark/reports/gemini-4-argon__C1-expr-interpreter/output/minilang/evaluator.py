import math
from .builtins import call_builtin
from .errors import EvalError
from .parser import (
    BinaryOp,
    BoolLiteral,
    Call,
    Identifier,
    NumberLiteral,
    StringLiteral,
    UnaryOp,
    parse,
)


def _eval_node(node: object, env: dict[str, object]) -> object:
    if isinstance(node, NumberLiteral):
        return node.value

    if isinstance(node, StringLiteral):
        return node.value

    if isinstance(node, BoolLiteral):
        return node.value

    if isinstance(node, Identifier):
        if node.name not in env:
            raise EvalError(f"undefined variable: {node.name}", node.position)
        val = env[node.name]
        if type(val) not in (float, str, bool):
            raise EvalError(f"unsupported value for {node.name}: {val!r}", node.position)
        return val

    if isinstance(node, UnaryOp):
        val = _eval_node(node.operand, env)
        if node.op == "-":
            if type(val) is not float:
                raise EvalError("unary '-' requires a number", node.position)
            return -val
        if node.op == "not":
            if type(val) is not bool:
                raise EvalError("'not' requires a boolean", node.position)
            return not val
        raise EvalError(f"unknown unary operator: {node.op}", node.position)

    if isinstance(node, BinaryOp):
        op = node.op

        if op == "and":
            left = _eval_node(node.left, env)
            if type(left) is not bool:
                raise EvalError("'and' requires boolean operands", node.position)
            if not left:
                return False
            right = _eval_node(node.right, env)
            if type(right) is not bool:
                raise EvalError("'and' requires boolean operands", node.position)
            return right

        if op == "or":
            left = _eval_node(node.left, env)
            if type(left) is not bool:
                raise EvalError("'or' requires boolean operands", node.position)
            if left:
                return True
            right = _eval_node(node.right, env)
            if type(right) is not bool:
                raise EvalError("'or' requires boolean operands", node.position)
            return right

        left = _eval_node(node.left, env)
        right = _eval_node(node.right, env)

        if op == "==":
            return type(left) is type(right) and left == right

        if op == "!=":
            return type(left) is not type(right) or left != right

        if op in ("<", "<=", ">", ">="):
            if not (
                (type(left) is float and type(right) is float)
                or (type(left) is str and type(right) is str)
            ):
                raise EvalError(
                    f"'{op}' requires two numbers or two strings", node.position
                )
            if op == "<":
                return left < right  # type: ignore[operator]
            if op == "<=":
                return left <= right  # type: ignore[operator]
            if op == ">":
                return left > right  # type: ignore[operator]
            return left >= right  # type: ignore[operator]

        if op == "+":
            if type(left) is float and type(right) is float:
                return left + right
            if type(left) is str and type(right) is str:
                return left + right
            raise EvalError("'+' requires two numbers or two strings", node.position)

        if op in ("-", "*", "/", "%", "^"):
            if type(left) is not float or type(right) is not float:
                raise EvalError(f"'{op}' requires number operands", node.position)
            if op == "-":
                return left - right
            if op == "*":
                return left * right
            if op == "/":
                if right == 0.0:
                    raise EvalError("division by zero", node.position)
                return left / right
            if op == "%":
                if right == 0.0:
                    raise EvalError("modulo by zero", node.position)
                return left % right
            if op == "^":
                try:
                    res = left ** right
                except (ZeroDivisionError, OverflowError, ValueError) as exc:
                    raise EvalError("invalid exponentiation", node.position) from exc
                if isinstance(res, complex) or not math.isfinite(res):
                    raise EvalError(
                        "exponentiation result is not a real number", node.position
                    )
                return float(res)

        raise EvalError(f"unknown binary operator: {op}", node.position)

    if isinstance(node, Call):
        return call_builtin(node.name, node.args, lambda arg: _eval_node(arg, env))

    raise EvalError(f"unknown AST node: {node!r}")


def evaluate(source: str, env: dict[str, object] | None = None) -> object:
    ast = parse(source)
    env_copy = dict(env) if env is not None else {}
    return _eval_node(ast, env_copy)
