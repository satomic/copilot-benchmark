"""MiniLang evaluator."""

from typing import Any
from .errors import EvalError
from .parser import BinaryOp, FunctionCall, Literal, UnaryOp, Variable, parse
from .builtins import ALL_BUILTINS, EAGER_BUILTINS


def evaluate_ast(node: Any, env: dict[str, Any]) -> Any:
    """Evaluate an AST node within the given environment."""
    if isinstance(node, Literal):
        return node.value

    if isinstance(node, Variable):
        if node.name not in env:
            raise EvalError(f"undefined variable: {node.name}", position=node.position)
        val = env[node.name]
        # Rule 26: env values must be float, str or bool. int values are not accepted.
        if type(val) not in (float, str, bool):
            raise EvalError(f"unsupported value for {node.name}: {val!r}", position=node.position)
        return val

    if isinstance(node, FunctionCall):
        name = node.name
        if name not in ALL_BUILTINS:
            raise EvalError(f"undefined function: {name}", position=node.position)
        if name == "if":
            if len(node.args) != 3:
                raise EvalError(f"if() takes 3 argument(s), got {len(node.args)}", position=node.position)
            cond = evaluate_ast(node.args[0], env)
            if type(cond) is not bool:
                raise EvalError("if() condition must be a boolean", position=node.position)
            if cond:
                return evaluate_ast(node.args[1], env)
            else:
                return evaluate_ast(node.args[2], env)

        # Eager evaluation of arguments for standard built-ins
        args = [evaluate_ast(arg, env) for arg in node.args]
        return EAGER_BUILTINS[name](args, position=node.position)

    if isinstance(node, UnaryOp):
        if node.op == "not":
            val = evaluate_ast(node.operand, env)
            if type(val) is not bool:
                raise EvalError("'not' requires a boolean", position=node.position)
            return not val
        elif node.op == "-":
            val = evaluate_ast(node.operand, env)
            if type(val) is not float:
                raise EvalError("unary '-' requires a number", position=node.position)
            return -val
        else:
            raise EvalError(f"unknown unary operator: {node.op}", position=node.position)

    if isinstance(node, BinaryOp):
        op = node.op
        # Short-circuit logical operators
        if op == "and":
            left = evaluate_ast(node.left, env)
            if type(left) is not bool:
                raise EvalError("left operand of 'and' must be a boolean", position=node.position)
            if not left:
                return False
            right = evaluate_ast(node.right, env)
            if type(right) is not bool:
                raise EvalError("right operand of 'and' must be a boolean", position=node.position)
            return right

        if op == "or":
            left = evaluate_ast(node.left, env)
            if type(left) is not bool:
                raise EvalError("left operand of 'or' must be a boolean", position=node.position)
            if left:
                return True
            right = evaluate_ast(node.right, env)
            if type(right) is not bool:
                raise EvalError("right operand of 'or' must be a boolean", position=node.position)
            return right

        # Standard binary operators
        left = evaluate_ast(node.left, env)
        right = evaluate_ast(node.right, env)

        if op == "+":
            if type(left) is float and type(right) is float:
                return left + right
            if type(left) is str and type(right) is str:
                return left + right
            raise EvalError(
                f"'+' requires two numbers or two strings, got {type(left).__name__} and {type(right).__name__}",
                position=node.position,
            )

        if op in ("-", "*", "/", "%", "^"):
            if type(left) is not float or type(right) is not float:
                raise EvalError(
                    f"'{op}' requires numbers, got {type(left).__name__} and {type(right).__name__}",
                    position=node.position,
                )
            if op == "-":
                return left - right
            if op == "*":
                return left * right
            if op == "/":
                if right == 0.0:
                    raise EvalError("division by zero", position=node.position)
                return left / right
            if op == "%":
                if right == 0.0:
                    raise EvalError("modulo by zero", position=node.position)
                return left % right
            if op == "^":
                if left == 0.0 and right < 0.0:
                    raise EvalError("division by zero", position=node.position)
                try:
                    res = left ** right
                except ZeroDivisionError:
                    raise EvalError("division by zero", position=node.position)
                except Exception as e:
                    raise EvalError(str(e), position=node.position)
                if isinstance(res, complex):
                    if res.imag != 0:
                        raise EvalError("result of ^ is not a real number", position=node.position)
                    res = res.real
                return float(res)

        if op == "==":
            if type(left) is not type(right):
                return False
            return left == right

        if op == "!=":
            if type(left) is not type(right):
                return True
            return left != right

        if op in ("<", "<=", ">", ">="):
            if (type(left) is float and type(right) is float) or (type(left) is str and type(right) is str):
                if op == "<":
                    return left < right
                if op == "<=":
                    return left <= right
                if op == ">":
                    return left > right
                if op == ">=":
                    return left >= right
            raise EvalError(
                f"'{op}' requires two numbers or two strings, got {type(left).__name__} and {type(right).__name__}",
                position=node.position,
            )

        raise EvalError(f"unknown binary operator: {op}", position=node.position)

    raise EvalError(f"unknown AST node type: {type(node).__name__}")


def evaluate(source: str, env: dict[str, Any] | None = None) -> object:
    """Evaluate source expression within the given environment."""
    ast = parse(source)
    env_mapping = env if env is not None else {}
    return evaluate_ast(ast, env_mapping)
