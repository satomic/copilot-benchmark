import math
from collections.abc import Mapping

from .builtins import BUILTINS, Value
from .errors import EvalError
from .parser import Binary, Call, Literal, Unary, Variable, parse


def _is_value(value: object) -> bool:
    return type(value) in {float, str, bool}


def _require_number(value: Value, operator: str) -> float:
    if type(value) is not float:
        raise EvalError(f"operator {operator} requires number operands")
    return value


def _require_boolean(value: Value, operator: str) -> bool:
    if type(value) is not bool:
        raise EvalError(f"operator {operator} requires boolean operands")
    return value


def _equal(left: Value, right: Value) -> bool:
    return type(left) is type(right) and left == right


def _evaluate_binary(operator: str, left: Value, right: Value) -> Value:
    if operator == "+":
        if type(left) is float and type(right) is float:
            return left + right
        if type(left) is str and type(right) is str:
            return left + right
        raise EvalError("operator + requires two numbers or two strings")

    if operator in {"-", "*", "/", "%", "^"}:
        left_number = _require_number(left, operator)
        right_number = _require_number(right, operator)
        if operator == "-":
            return left_number - right_number
        if operator == "*":
            return left_number * right_number
        if operator == "/":
            if right_number == 0.0:
                raise EvalError("division by zero")
            return left_number / right_number
        if operator == "%":
            if right_number == 0.0:
                raise EvalError("modulo by zero")
            return left_number % right_number
        try:
            result = left_number**right_number
        except (OverflowError, ZeroDivisionError, ValueError) as error:
            raise EvalError("invalid power operation") from error
        if type(result) is not float or not math.isfinite(result):
            raise EvalError("power result is not a real number")
        return result

    if operator == "==":
        return _equal(left, right)
    if operator == "!=":
        return not _equal(left, right)
    if operator in {"<", "<=", ">", ">="}:
        comparable = (
            type(left) is float and type(right) is float
        ) or (
            type(left) is str and type(right) is str
        )
        if not comparable:
            raise EvalError(
                f"operator {operator} requires two numbers or two strings"
            )
        if operator == "<":
            return left < right
        if operator == "<=":
            return left <= right
        if operator == ">":
            return left > right
        return left >= right
    raise EvalError(f"unknown operator: {operator}")


def _evaluate(node: object, env: Mapping[str, object]) -> Value:
    if isinstance(node, Literal):
        return node.value  # type: ignore[return-value]
    if isinstance(node, Variable):
        if node.name not in env:
            raise EvalError(f"undefined variable: {node.name}")
        value = env[node.name]
        if not _is_value(value):
            raise EvalError(f"unsupported value for {node.name}: {value!r}")
        return value  # type: ignore[return-value]
    if isinstance(node, Unary):
        value = _evaluate(node.operand, env)
        if node.operator == "-":
            return -_require_number(value, "-")
        return not _require_boolean(value, "not")
    if isinstance(node, Binary):
        left = _evaluate(node.left, env)
        if node.operator == "and":
            left_boolean = _require_boolean(left, "and")
            if not left_boolean:
                return False
            return _require_boolean(_evaluate(node.right, env), "and")
        if node.operator == "or":
            left_boolean = _require_boolean(left, "or")
            if left_boolean:
                return True
            return _require_boolean(_evaluate(node.right, env), "or")
        return _evaluate_binary(node.operator, left, _evaluate(node.right, env))
    if isinstance(node, Call):
        if node.name == "if":
            if len(node.arguments) != 3:
                raise EvalError(
                    f"if() takes 3 argument(s), got {len(node.arguments)}"
                )
            condition = _require_boolean(
                _evaluate(node.arguments[0], env), "if"
            )
            branch = node.arguments[1] if condition else node.arguments[2]
            return _evaluate(branch, env)
        function = BUILTINS.get(node.name)
        if function is None:
            raise EvalError(f"undefined function: {node.name}")
        return function([_evaluate(argument, env) for argument in node.arguments])
    raise EvalError("invalid syntax tree")


def evaluate(source: str, env: dict | None = None) -> object:
    environment: Mapping[str, object] = {} if env is None else env
    return _evaluate(parse(source), environment)
