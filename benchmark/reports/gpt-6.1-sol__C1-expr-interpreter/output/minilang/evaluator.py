from .builtins import FUNCTIONS, Value, require_boolean, require_number
from .errors import EvalError
from .parser import Binary, Call, Literal, Node, Unary, Variable, parse


def _binary(operator: str, left: Value, right: Value) -> Value:
    if operator in {"==", "!="}:
        equal = type(left) is type(right) and left == right
        return equal if operator == "==" else not equal
    if operator in {"<", "<=", ">", ">="}:
        if type(left) is not type(right) or type(left) not in {float, str}:
            raise EvalError(f"{operator} requires two numbers or two strings")
        if operator == "<":
            return left < right
        if operator == "<=":
            return left <= right
        if operator == ">":
            return left > right
        return left >= right
    if operator == "+" and type(left) is str and type(right) is str:
        return left + right
    a = require_number(left, operator)
    b = require_number(right, operator)
    if operator == "+":
        return a + b
    if operator == "-":
        return a - b
    if operator == "*":
        return a * b
    if operator == "/":
        if b == 0.0:
            raise EvalError("division by zero")
        return a / b
    if operator == "%":
        if b == 0.0:
            raise EvalError("modulo by zero")
        return a % b
    try:
        result = a ** b
    except (OverflowError, ValueError, ZeroDivisionError) as error:
        raise EvalError(f"invalid exponentiation: {error}") from error
    if type(result) is not float:
        raise EvalError("exponentiation result is not a real number")
    return result


def _evaluate(node: Node, env: dict) -> Value:
    if isinstance(node, Literal):
        return node.value
    if isinstance(node, Variable):
        if node.name not in env:
            raise EvalError(f"undefined variable: {node.name}")
        value = env[node.name]
        if type(value) not in {float, str, bool}:
            raise EvalError(f"unsupported value for {node.name}: {value!r}")
        return value
    if isinstance(node, Unary):
        value = _evaluate(node.operand, env)
        if node.operator == "not":
            return not require_boolean(value, "not")
        return -require_number(value, "unary minus")
    if isinstance(node, Binary):
        left = _evaluate(node.left, env)
        if node.operator in {"and", "or"}:
            boolean = require_boolean(left, node.operator)
            if node.operator == "and" and not boolean:
                return False
            if node.operator == "or" and boolean:
                return True
            return require_boolean(_evaluate(node.right, env), node.operator)
        return _binary(node.operator, left, _evaluate(node.right, env))
    if isinstance(node, Call):
        builtin = FUNCTIONS.get(node.name)
        if builtin is None:
            raise EvalError(f"undefined function: {node.name}")
        builtin.check_arity(node.name, len(node.arguments))
        if node.name == "if":
            condition = require_boolean(_evaluate(node.arguments[0], env), "if()")
            return _evaluate(node.arguments[1 if condition else 2], env)
        arguments = [_evaluate(argument, env) for argument in node.arguments]
        assert builtin.function is not None
        try:
            return builtin.function(arguments)
        except (OverflowError, ValueError) as error:
            raise EvalError(f"{node.name}(): {error}") from error
    raise TypeError(f"unsupported AST node: {node!r}")


def evaluate(source: str, env: dict | None = None) -> Value:
    return _evaluate(parse(source), {} if env is None else env)
