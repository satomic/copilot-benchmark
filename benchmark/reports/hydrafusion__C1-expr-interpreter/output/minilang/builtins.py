import math
from collections.abc import Callable

from .errors import EvalError


Value = float | str | bool
Builtin = Callable[[list[Value]], Value]


def format_number(value: float) -> str:
    if math.isfinite(value) and value.is_integer():
        return str(int(value))
    return repr(value)


def _arity(name: str, arguments: list[Value], expected: int) -> None:
    if len(arguments) != expected:
        raise EvalError(
            f"{name}() takes {expected} argument(s), got {len(arguments)}"
        )


def _arity_range(
    name: str, arguments: list[Value], expected: str, allowed: set[int]
) -> None:
    if len(arguments) not in allowed:
        raise EvalError(
            f"{name}() takes {expected} argument(s), got {len(arguments)}"
        )


def _number(name: str, value: Value) -> float:
    if type(value) is not float:
        raise EvalError(f"{name}() requires number argument(s)")
    return value


def _string(name: str, value: Value) -> str:
    if type(value) is not str:
        raise EvalError(f"{name}() requires string argument(s)")
    return value


def _abs(arguments: list[Value]) -> Value:
    _arity("abs", arguments, 1)
    return abs(_number("abs", arguments[0]))


def _min(arguments: list[Value]) -> Value:
    if not arguments:
        raise EvalError("min() takes at least 1 argument(s), got 0")
    return min(_number("min", value) for value in arguments)


def _max(arguments: list[Value]) -> Value:
    if not arguments:
        raise EvalError("max() takes at least 1 argument(s), got 0")
    return max(_number("max", value) for value in arguments)


def _round(arguments: list[Value]) -> Value:
    _arity_range("round", arguments, "1 or 2", {1, 2})
    value = _number("round", arguments[0])
    if len(arguments) == 1:
        return float(round(value))
    digits = _number("round", arguments[1])
    if not math.isfinite(digits) or not digits.is_integer():
        raise EvalError("round() second argument must be a whole number")
    return float(round(value, int(digits)))


def _len(arguments: list[Value]) -> Value:
    _arity("len", arguments, 1)
    return float(len(_string("len", arguments[0])))


def _upper(arguments: list[Value]) -> Value:
    _arity("upper", arguments, 1)
    return _string("upper", arguments[0]).upper()


def _lower(arguments: list[Value]) -> Value:
    _arity("lower", arguments, 1)
    return _string("lower", arguments[0]).lower()


def _str(arguments: list[Value]) -> Value:
    _arity("str", arguments, 1)
    value = arguments[0]
    if type(value) is bool:
        return "true" if value else "false"
    if type(value) is float:
        return format_number(value)
    return value


def _num(arguments: list[Value]) -> Value:
    _arity("num", arguments, 1)
    value = _string("num", arguments[0])
    try:
        return float(value)
    except ValueError as error:
        raise EvalError(f"num() could not parse {value!r}") from error


BUILTINS: dict[str, Builtin] = {
    "abs": _abs,
    "min": _min,
    "max": _max,
    "round": _round,
    "len": _len,
    "upper": _upper,
    "lower": _lower,
    "str": _str,
    "num": _num,
}
