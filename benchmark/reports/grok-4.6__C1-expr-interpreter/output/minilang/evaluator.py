import math

from minilang.builtins import FUNCTIONS, format_value
from minilang.errors import EvalError
from minilang.parser import Binary, BoolLit, Call, NumberLit, StringLit, Unary, Variable, parse

_ALLOWED = (float, str, bool)


def _is_number(value) -> bool:
    return isinstance(value, float) and not isinstance(value, bool)


def evaluate(source: str, env: dict | None = None):
    tree = parse(source)
    return eval_node(tree, env)


def eval_node(node, env: dict | None):
    if isinstance(node, NumberLit):
        return node.value
    if isinstance(node, StringLit):
        return node.value
    if isinstance(node, BoolLit):
        return node.value
    if isinstance(node, Variable):
        return _lookup_var(node.name, env)
    if isinstance(node, Unary):
        return _eval_unary(node, env)
    if isinstance(node, Binary):
        return _eval_binary(node, env)
    if isinstance(node, Call):
        return _eval_call(node, env)
    raise EvalError(f"unknown AST node: {type(node).__name__}")


def _lookup_var(name: str, env: dict | None):
    if env is None or name not in env:
        raise EvalError(f"undefined variable: {name}")
    value = env[name]
    if not isinstance(value, _ALLOWED) or type(value) not in (float, str, bool):
        raise EvalError(f"unsupported value for {name}: {value!r}")
    return value


def _eval_unary(node: Unary, env):
    if node.op == "not":
        operand = eval_node(node.operand, env)
        if not isinstance(operand, bool):
            raise EvalError("not requires a boolean")
        return not operand
    if node.op == "-":
        operand = eval_node(node.operand, env)
        if not _is_number(operand):
            raise EvalError("unary minus requires a number")
        return -operand
    raise EvalError(f"unknown unary operator: {node.op}")


def _eval_binary(node: Binary, env):
    op = node.op
    if op in ("and", "or"):
        left = eval_node(node.left, env)
        if not isinstance(left, bool):
            raise EvalError(f"{op} requires boolean operands")
        if op == "and":
            if not left:
                return False
        else:
            if left:
                return True
        right = eval_node(node.right, env)
        if not isinstance(right, bool):
            raise EvalError(f"{op} requires boolean operands")
        return right

    left = eval_node(node.left, env)
    right = eval_node(node.right, env)

    if op == "+":
        if _is_number(left) and _is_number(right):
            return left + right
        if isinstance(left, str) and isinstance(right, str):
            return left + right
        raise EvalError("+ requires two numbers or two strings")
    if op == "-":
        _require_nums(op, left, right)
        return left - right
    if op == "*":
        _require_nums(op, left, right)
        return left * right
    if op == "/":
        _require_nums(op, left, right)
        if right == 0.0:
            raise EvalError("division by zero")
        return left / right
    if op == "%":
        _require_nums(op, left, right)
        if right == 0.0:
            raise EvalError("modulo by zero")
        return left % right
    if op == "^":
        _require_nums(op, left, right)
        try:
            result = left ** right
        except ZeroDivisionError:
            raise EvalError("invalid power") from None
        except OverflowError:
            raise EvalError("invalid power") from None
        if isinstance(result, complex) or (
            isinstance(result, float) and math.isnan(result)
        ):
            raise EvalError("power result is not a real number")
        if isinstance(result, bool) or not isinstance(result, (float, int)):
            raise EvalError("power result is not a real number")
        return float(result)
    if op in ("==", "!="):
        equal = _values_equal(left, right)
        return equal if op == "==" else (not equal)
    if op in ("<", "<=", ">", ">="):
        if _is_number(left) and _is_number(right):
            pair = (left, right)
        elif isinstance(left, str) and isinstance(right, str):
            pair = (left, right)
        else:
            raise EvalError(f"{op} requires two numbers or two strings")
        a, b = pair
        if op == "<":
            return a < b
        if op == "<=":
            return a <= b
        if op == ">":
            return a > b
        return a >= b
    raise EvalError(f"unknown operator: {op}")


def _values_equal(left, right) -> bool:
    if isinstance(left, bool) or isinstance(right, bool):
        return isinstance(left, bool) and isinstance(right, bool) and left is right
    return type(left) is type(right) and left == right


def _require_nums(op, left, right):
    if not (_is_number(left) and _is_number(right)):
        raise EvalError(f"{op} requires numbers")


def _eval_call(node: Call, env):
    name = node.name
    if name == "if":
        if len(node.args) != 3:
            raise EvalError(f"if() takes 3 argument(s), got {len(node.args)}")
        cond = eval_node(node.args[0], env)
        if not isinstance(cond, bool):
            raise EvalError("if() condition must be a boolean")
        return eval_node(node.args[1] if cond else node.args[2], env)
    if name not in FUNCTIONS:
        raise EvalError(f"undefined function: {name}")
    args = [eval_node(arg, env) for arg in node.args]
    return FUNCTIONS[name](args)


# Re-export for the REPL.
format_value = format_value
