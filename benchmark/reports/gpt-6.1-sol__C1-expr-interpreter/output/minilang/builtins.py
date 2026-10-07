import builtins as python
from dataclasses import dataclass
from typing import Callable

from .errors import EvalError


Value = float | str | bool


def format_value(value: Value, quote_strings: bool = True) -> str:
    if type(value) is bool:
        return "true" if value else "false"
    if type(value) is float:
        return python.str(int(value)) if value.is_integer() else repr(value)
    if not quote_strings:
        return value
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    escaped = escaped.replace("\n", "\\n").replace("\t", "\\t").replace("\r", "\\r")
    return '"' + escaped + '"'


def require_number(value: Value, context: str) -> float:
    if type(value) is not float:
        raise EvalError(f"{context} requires a number")
    return value


def require_boolean(value: Value, context: str) -> bool:
    if type(value) is not bool:
        raise EvalError(f"{context} requires a boolean")
    return value


def require_string(value: Value, context: str) -> str:
    if type(value) is not str:
        raise EvalError(f"{context} requires a string")
    return value


def _abs(arguments: list[Value]) -> Value:
    return python.abs(require_number(arguments[0], "abs()"))


def _min(arguments: list[Value]) -> Value:
    return python.min(require_number(value, "min()") for value in arguments)


def _max(arguments: list[Value]) -> Value:
    return python.max(require_number(value, "max()") for value in arguments)


def _round(arguments: list[Value]) -> Value:
    number = require_number(arguments[0], "round()")
    if len(arguments) == 1:
        return float(python.round(number))
    digits = require_number(arguments[1], "round()")
    if not digits.is_integer():
        raise EvalError("round() requires a whole number of digits")
    return float(python.round(number, int(digits)))


def _len(arguments: list[Value]) -> Value:
    return float(python.len(require_string(arguments[0], "len()")))


def _upper(arguments: list[Value]) -> Value:
    return require_string(arguments[0], "upper()").upper()


def _lower(arguments: list[Value]) -> Value:
    return require_string(arguments[0], "lower()").lower()


def _str(arguments: list[Value]) -> Value:
    return format_value(arguments[0], quote_strings=False)


def _num(arguments: list[Value]) -> Value:
    text = require_string(arguments[0], "num()")
    try:
        return float(text)
    except ValueError as error:
        raise EvalError(f"num() cannot convert {text!r} to a number") from error


@dataclass(frozen=True)
class Builtin:
    minimum: int
    maximum: int | None
    expected: str
    function: Callable[[list[Value]], Value] | None

    def check_arity(self, name: str, count: int) -> None:
        if count < self.minimum or (self.maximum is not None and count > self.maximum):
            raise EvalError(
                f"{name}() takes {self.expected} argument(s), got {count}"
            )


# Variable arities use descriptive expected counts in the prescribed message.
FUNCTIONS = {
    "abs": Builtin(1, 1, "1", _abs),
    "min": Builtin(1, None, "at least 1", _min),
    "max": Builtin(1, None, "at least 1", _max),
    "round": Builtin(1, 2, "1 or 2", _round),
    "len": Builtin(1, 1, "1", _len),
    "upper": Builtin(1, 1, "1", _upper),
    "lower": Builtin(1, 1, "1", _lower),
    "str": Builtin(1, 1, "1", _str),
    "num": Builtin(1, 1, "1", _num),
    "if": Builtin(3, 3, "3", None),
}
