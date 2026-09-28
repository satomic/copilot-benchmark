import math

from .builtins import BUILTIN_NAMES, call_builtin, check_arity
from .errors import EvalError
from .parser import Binary, Call, Literal, Unary, Variable, parse


def _number(value: object, operator: str) -> float:
    if type(value) is not float:
        raise EvalError(f"operator {operator} requires numbers")
    return value


def _boolean(value: object, operator: str) -> bool:
    if type(value) is not bool:
        raise EvalError(f"operator {operator} requires booleans")
    return value


def _eval(node: object, env: dict) -> object:
    if isinstance(node, Literal):
        return node.value
    if isinstance(node, Variable):
        if node.name not in env:
            raise EvalError(f"undefined variable: {node.name}")
        value = env[node.name]
        if type(value) not in (float, str, bool):
            raise EvalError(f"unsupported value for {node.name}: {value!r}")
        return value
    if isinstance(node, Unary):
        value = _eval(node.operand, env)
        if node.operator == "not":
            return not _boolean(value, "not")
        return -_number(value, "-")
    if isinstance(node, Binary):
        left = _eval(node.left, env)
        if node.operator == "and":
            left_bool = _boolean(left, "and")
            return _boolean(_eval(node.right, env), "and") if left_bool else False
        if node.operator == "or":
            left_bool = _boolean(left, "or")
            return True if left_bool else _boolean(_eval(node.right, env), "or")
        right = _eval(node.right, env)
        operator = node.operator
        if operator == "+":
            if type(left) is float and type(right) is float:
                return left + right
            if type(left) is str and type(right) is str:
                return left + right
            raise EvalError("operator + requires two numbers or two strings")
        if operator in ("-", "*", "/", "%", "^"):
            first = _number(left, operator)
            second = _number(right, operator)
            if operator == "-":
                return first - second
            if operator == "*":
                return first * second
            if operator == "/":
                if second == 0.0:
                    raise EvalError("division by zero")
                return first / second
            if operator == "%":
                if second == 0.0:
                    raise EvalError("modulo by zero")
                return first % second
            try:
                result = first ** second
            except (OverflowError, ValueError, ZeroDivisionError) as error:
                raise EvalError("power result is not a real number") from error
            if type(result) is not float or not math.isfinite(result) and math.isfinite(first):
                raise EvalError("power result is not a real number")
            return result
        if operator in ("==", "!="):
            equal = type(left) is type(right) and left == right
            return equal if operator == "==" else not equal
        if operator in ("<", "<=", ">", ">="):
            if type(left) is not type(right) or type(left) not in (float, str):
                raise EvalError(f"operator {operator} requires two numbers or two strings")
            if operator == "<":
                return left < right
            if operator == "<=":
                return left <= right
            if operator == ">":
                return left > right
            return left >= right
    if isinstance(node, Call):
        if node.name not in BUILTIN_NAMES:
            raise EvalError(f"undefined function: {node.name}")
        check_arity(node.name, len(node.arguments))
        if node.name == "if":
            condition = _boolean(_eval(node.arguments[0], env), "if")
            return _eval(node.arguments[1] if condition else node.arguments[2], env)
        return call_builtin(node.name, [_eval(argument, env) for argument in node.arguments])
    raise EvalError("invalid expression")


def evaluate(source: str, env: dict | None = None) -> object:
    return _eval(parse(source), {} if env is None else env)
