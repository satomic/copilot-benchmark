import math

from .builtins import BUILTINS
from .errors import EvalError
from .parser import BinaryNode, BoolNode, CallNode, NameNode, NumberNode, StringNode, UnaryNode


def _is_bool(value) -> bool:
    return type(value) is bool


def _value_from_env(name: str, env):
    if name not in env:
        raise EvalError(f"undefined variable: {name}")
    value = env[name]
    if type(value) in (float, str, bool):
        return value
    raise EvalError(f"unsupported value for {name}: {value!r}")


def evaluate_node(node, env):
    if isinstance(node, NumberNode):
        return node.value

    if isinstance(node, StringNode):
        return node.value

    if isinstance(node, BoolNode):
        return node.value

    if isinstance(node, NameNode):
        return _value_from_env(node.name, env)

    if isinstance(node, UnaryNode):
        operand = evaluate_node(node.operand, env)
        if node.op == "-":
            if type(operand) is not float:
                raise EvalError("unary minus requires a number")
            return -operand
        if node.op == "not":
            if type(operand) is not bool:
                raise EvalError("not requires a boolean")
            return not operand
        raise EvalError(f"unsupported unary operator: {node.op}")

    if isinstance(node, BinaryNode):
        op = node.op
        if op == "and":
            left = evaluate_node(node.left, env)
            if type(left) is not bool:
                raise EvalError("and requires booleans")
            if not left:
                return False
            right = evaluate_node(node.right, env)
            if type(right) is not bool:
                raise EvalError("and requires booleans")
            return right

        if op == "or":
            left = evaluate_node(node.left, env)
            if type(left) is not bool:
                raise EvalError("or requires booleans")
            if left:
                return True
            right = evaluate_node(node.right, env)
            if type(right) is not bool:
                raise EvalError("or requires booleans")
            return right

        left = evaluate_node(node.left, env)
        right = evaluate_node(node.right, env)

        if op == "+":
            if type(left) is float and type(right) is float:
                return left + right
            if type(left) is str and type(right) is str:
                return left + right
            raise EvalError("+ requires two numbers or two strings")

        if op == "-":
            if type(left) is not float or type(right) is not float:
                raise EvalError("- requires numbers")
            return left - right

        if op == "*":
            if type(left) is not float or type(right) is not float:
                raise EvalError("* requires numbers")
            return left * right

        if op == "/":
            if type(left) is not float or type(right) is not float:
                raise EvalError("/ requires numbers")
            if right == 0.0:
                raise EvalError("division by zero")
            return left / right

        if op == "%":
            if type(left) is not float or type(right) is not float:
                raise EvalError("% requires numbers")
            if right == 0.0:
                raise EvalError("modulo by zero")
            return left % right

        if op == "^":
            if type(left) is not float or type(right) is not float:
                raise EvalError("^ requires numbers")
            try:
                result = left ** right
            except (OverflowError, ValueError):
                raise EvalError("result is not a real number") from None
            if isinstance(result, complex) or not math.isfinite(result):
                raise EvalError("result is not a real number")
            return float(result)

        if op == "==":
            if type(left) is not type(right):
                return False
            return left == right

        if op == "!=":
            if type(left) is not type(right):
                return True
            return left != right

        if op in {"<", "<=", ">", ">="}:
            if type(left) is float and type(right) is float:
                if op == "<":
                    return left < right
                if op == "<=":
                    return left <= right
                if op == ">":
                    return left > right
                return left >= right
            if type(left) is str and type(right) is str:
                if op == "<":
                    return left < right
                if op == "<=":
                    return left <= right
                if op == ">":
                    return left > right
                return left >= right
            raise EvalError("comparison requires numbers or strings")

        raise EvalError(f"unsupported operator: {op}")

    if isinstance(node, CallNode):
        name = node.name
        if name == "if":
            if len(node.args) != 3:
                raise EvalError(f"if() takes 3 argument(s), got {len(node.args)}")
            cond = evaluate_node(node.args[0], env)
            if type(cond) is not bool:
                raise EvalError("if() requires a boolean condition")
            if cond:
                return evaluate_node(node.args[1], env)
            return evaluate_node(node.args[2], env)

        if name not in BUILTINS:
            raise EvalError(f"undefined function: {name}")

        evaluated = [evaluate_node(arg, env) for arg in node.args]
        return BUILTINS[name](evaluated)

    raise EvalError(f"unsupported node type: {type(node).__name__}")


def evaluate(source: str, env: dict | None = None):
    from .parser import parse

    if env is None:
        local_env = {}
    else:
        local_env = dict(env)
    return evaluate_node(parse(source), local_env)
