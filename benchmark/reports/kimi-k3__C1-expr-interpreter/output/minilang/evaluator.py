"""Evaluator for minilang ASTs."""

from .builtins import BUILTINS, typename
from .errors import EvalError
from .parser import Binary, Bool, Call, Num, Str, Unary, Var, parse


def evaluate(source, env=None):
    """Parse and evaluate source, returning a float, str or bool.

    The given env mapping is only read, never mutated.
    """
    node = parse(source)
    return _eval(node, env if env is not None else {})


def _require_bool(value, context):
    if type(value) is not bool:
        raise EvalError(f"{context} requires a boolean, got {typename(value)}")
    return value


def _require_number(value, context):
    if type(value) is not float:
        raise EvalError(f"{context} requires a number, got {typename(value)}")
    return value


def _eval(node, env):
    if isinstance(node, (Num, Str, Bool)):
        return node.value

    if isinstance(node, Var):
        if node.name not in env:
            raise EvalError(f"undefined variable: {node.name}")
        value = env[node.name]
        if type(value) not in (float, str, bool):
            raise EvalError(f"unsupported value for {node.name}: {value!r}")
        return value

    if isinstance(node, Unary):
        if node.op == "not":
            return not _require_bool(_eval(node.operand, env), "not")
        return -_require_number(_eval(node.operand, env), "unary '-'")

    if isinstance(node, Binary):
        return _eval_binary(node, env)

    # Call
    if node.name == "if":
        # Lazy conditional: only the taken branch is evaluated.
        if len(node.args) != 3:
            raise EvalError(f"if() takes 3 argument(s), got {len(node.args)}")
        cond = _require_bool(_eval(node.args[0], env), "if() condition")
        return _eval(node.args[1] if cond else node.args[2], env)

    fn = BUILTINS.get(node.name)
    if fn is None:
        # No fall-back to variables: a call target must be a built-in.
        raise EvalError(f"undefined function: {node.name}")
    return fn([_eval(arg, env) for arg in node.args])


def _eval_binary(node, env):
    op = node.op

    if op == "and":
        left = _require_bool(_eval(node.left, env), "and")
        if not left:
            return False
        return _require_bool(_eval(node.right, env), "and")

    if op == "or":
        left = _require_bool(_eval(node.left, env), "or")
        if left:
            return True
        return _require_bool(_eval(node.right, env), "or")

    left = _eval(node.left, env)
    right = _eval(node.right, env)

    if op == "+":
        if type(left) is float and type(right) is float:
            return left + right
        if type(left) is str and type(right) is str:
            return left + right
        raise EvalError(f"cannot add {typename(left)} and {typename(right)}")

    if op in ("-", "*", "/", "%"):
        _require_number(left, f"'{op}'")
        _require_number(right, f"'{op}'")
        if op == "-":
            return left - right
        if op == "*":
            return left * right
        if op == "/":
            if right == 0.0:
                raise EvalError("division by zero")
            return left / right
        if right == 0.0:
            raise EvalError("modulo by zero")
        return left % right  # Python semantics: result takes divisor's sign

    if op == "^":
        _require_number(left, "'^'")
        _require_number(right, "'^'")
        try:
            result = left ** right
        except (OverflowError, ZeroDivisionError) as exc:
            raise EvalError(f"invalid power operation: {exc}") from None
        if isinstance(result, complex):
            raise EvalError("power result is not a real number")
        return result

    if op == "==":
        # Different types are never equal (True == 1.0 must be False).
        return type(left) is type(right) and left == right

    if op == "!=":
        return not (type(left) is type(right) and left == right)

    # Ordering comparisons: numbers with numbers, strings with strings.
    same_orderable = (type(left) is float and type(right) is float) or (
        type(left) is str and type(right) is str
    )
    if not same_orderable:
        raise EvalError(f"cannot compare {typename(left)} with {typename(right)}")
    if op == "<":
        return left < right
    if op == "<=":
        return left <= right
    if op == ">":
        return left > right
    return left >= right
