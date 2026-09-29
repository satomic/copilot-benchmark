import math
from minilang.errors import EvalError
from minilang.parser import (
    NumberLiteral, StringLiteral, BooleanLiteral,
    Identifier, UnaryOp, BinaryOp, FunctionCall,
    parse as _parse,
)
from minilang.builtins import BUILTINS


def evaluate(source: str, env: dict | None = None) -> object:
    """Parse and evaluate a minilang expression."""
    if env is None:
        env = {}
    # Deep-copy the env so we don't mutate the caller's dict
    env_copy = dict(env)
    ast = _parse(source)
    return _eval_node(ast, env_copy)


def _eval_node(node: object, env: dict) -> object:
    """Evaluate an AST node in the given environment."""

    if isinstance(node, NumberLiteral):
        return node.value

    if isinstance(node, StringLiteral):
        return node.value

    if isinstance(node, BooleanLiteral):
        return node.value

    if isinstance(node, Identifier):
        return _resolve_name(node.name, node.position, env)

    if isinstance(node, UnaryOp):
        if node.op == "-":
            val = _eval_node(node.operand, env)
            if not isinstance(val, (int, float)):
                raise EvalError("unary minus requires a number", node.position)
            return -val
        elif node.op == "not":
            val = _eval_node(node.operand, env)
            if not isinstance(val, bool):
                raise EvalError("not requires a boolean", node.position)
            return not val
        else:
            raise EvalError(f"unknown unary operator: {node.op}", node.position)

    if isinstance(node, BinaryOp):
        return _eval_binary(node, env)

    if isinstance(node, FunctionCall):
        return _eval_call(node, env)

    raise EvalError(f"unknown AST node: {type(node)}")


def _resolve_name(name: str, position: int, env: dict) -> object:
    """Look up a name in the environment."""
    if name in env:
        val = env[name]
        if isinstance(val, bool):
            return val
        if isinstance(val, float):
            return val
        if isinstance(val, str):
            return val
        if isinstance(val, int):
            raise EvalError(f"unsupported value for {name}: {val!r}", position)
        raise EvalError(f"unsupported value for {name}: {val!r}", position)
    # Check built-ins (as variable access, not function call - this should raise)
    if name in BUILTINS:
        raise EvalError(f"undefined variable: {name}", position)
    raise EvalError(f"undefined variable: {name}", position)


def _eval_binary(node: BinaryOp, env: dict) -> object:
    op = node.op

    # Short-circuit logical operators
    if op == "or":
        left = _eval_node(node.left, env)
        if not isinstance(left, bool):
            raise EvalError("or requires boolean operands", node.position)
        if left:
            return True
        right = _eval_node(node.right, env)
        if not isinstance(right, bool):
            raise EvalError("or requires boolean operands", node.position)
        return right

    if op == "and":
        left = _eval_node(node.left, env)
        if not isinstance(left, bool):
            raise EvalError("and requires boolean operands", node.position)
        if not left:
            return False
        right = _eval_node(node.right, env)
        if not isinstance(right, bool):
            raise EvalError("and requires boolean operands", node.position)
        return right

    left = _eval_node(node.left, env)
    right = _eval_node(node.right, env)

    if op == "+":
        if isinstance(left, float) and isinstance(right, float):
            return left + right
        if isinstance(left, str) and isinstance(right, str):
            return left + right
        raise EvalError(
            f"cannot add {type(left).__name__} and {type(right).__name__}",
            node.position,
        )

    if op == "-":
        _check_numeric_binary(op, left, right, node.position)
        return left - right

    if op == "*":
        _check_numeric_binary(op, left, right, node.position)
        return left * right

    if op == "/":
        _check_numeric_binary(op, left, right, node.position)
        if right == 0.0:
            raise EvalError("division by zero", node.position)
        return left / right

    if op == "%":
        _check_numeric_binary(op, left, right, node.position)
        if right == 0.0:
            raise EvalError("modulo by zero", node.position)
        return left % right

    if op == "^":
        _check_numeric_binary(op, left, right, node.position)
        result = left ** right
        if isinstance(result, complex) or result != result:
            raise EvalError("result is not a real number", node.position)
        return result

    if op in ("==", "!="):
        if type(left) != type(right):
            eq = False
        else:
            eq = left == right
        if op == "==":
            return eq
        else:
            return not eq

    if op in ("<", "<=", ">", ">="):
        if isinstance(left, float) and isinstance(right, float):
            pass  # OK
        elif isinstance(left, str) and isinstance(right, str):
            pass  # OK
        else:
            raise EvalError(
                f"cannot compare {type(left).__name__} and {type(right).__name__}",
                node.position,
            )
        if op == "<":
            return left < right
        elif op == "<=":
            return left <= right
        elif op == ">":
            return left > right
        else:  # >=
            return left >= right

    raise EvalError(f"unknown operator: {op}", node.position)


def _check_numeric_binary(op: str, left: object, right: object, position: int):
    if not (isinstance(left, float) and isinstance(right, float)):
        raise EvalError(
            f"{op} requires numbers, got {type(left).__name__} and {type(right).__name__}",
            position,
        )


def _eval_call(node: FunctionCall, env: dict) -> object:
    name = node.name

    # Special handling for lazy if
    if name == "if":
        if len(node.args) != 3:
            raise EvalError(
                f"if() takes 3 argument(s), got {len(node.args)}", node.position
            )
        # Evaluate condition only
        cond = _eval_node(node.args[0], env)
        if not isinstance(cond, bool):
            raise EvalError("if() condition must be a boolean", node.position)
        if cond:
            return _eval_node(node.args[1], env)
        else:
            return _eval_node(node.args[2], env)

    # Check if it's a built-in
    if name in BUILTINS:
        args = []
        for arg_node in node.args:
            args.append(_eval_node(arg_node, env))
        return BUILTINS[name](args)

    # Unknown function
    raise EvalError(f"undefined function: {name}", node.position)