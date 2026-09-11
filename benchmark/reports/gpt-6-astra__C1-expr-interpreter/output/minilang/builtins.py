from dataclasses import dataclass
from typing import Callable, TypeAlias

from .errors import EvalError


Value: TypeAlias = float | str | bool


def require_number(value: Value) -> float:
    if type(value) is not float:
        raise EvalError("expected number")
    return value


def require_boolean(value: Value) -> bool:
    if type(value) is not bool:
        raise EvalError("expected boolean")
    return value


def require_string(value: Value) -> str:
    if type(value) is not str:
        raise EvalError("expected string")
    return value


def value_text(value: Value) -> str:
    if type(value) is bool:
        return "true" if value else "false"
    if isinstance(value, float):
        return str(int(value)) if value.is_integer() else repr(value)
    return require_string(value)


def format_value(value: Value) -> str:
    if type(value) is str:
        escaped = value.replace("\\", "\\\\").replace('"', '\\"')
        escaped = escaped.replace("\n", "\\n").replace("\t", "\\t").replace("\r", "\\r")
        return f'"{escaped}"'
    return value_text(value)


def _round(arguments: list[Value]) -> float:
    number = require_number(arguments[0])
    if len(arguments) == 1:
        return float(round(number))
    digits = require_number(arguments[1])
    if not digits.is_integer():
        raise EvalError("round() requires a whole number for n")
    return float(round(number, int(digits)))


def _num(arguments: list[Value]) -> float:
    text = require_string(arguments[0])
    try:
        # num accepts Python float syntax, including whitespace and non-finite values.
        return float(text)
    except ValueError as error:
        raise EvalError(f"invalid number: {text!r}") from error


@dataclass(frozen=True)
class _Builtin:
    minimum: int
    maximum: int | None
    function: Callable[[list[Value]], Value] | None

    def check_arity(self, name: str, count: int) -> None:
        if count >= self.minimum and (self.maximum is None or count <= self.maximum):
            return
        # Variable arities use "at least 1" and "1 or 2" in the expected field.
        if self.maximum is None:
            expected = f"at least {self.minimum}"
        elif self.minimum == self.maximum:
            expected = str(self.minimum)
        else:
            expected = f"{self.minimum} or {self.maximum}"
        raise EvalError(f"{name}() takes {expected} argument(s), got {count}")


_BUILTINS = {
    "abs": _Builtin(1, 1, lambda args: abs(require_number(args[0]))),
    "min": _Builtin(1, None, lambda args: min(require_number(arg) for arg in args)),
    "max": _Builtin(1, None, lambda args: max(require_number(arg) for arg in args)),
    "round": _Builtin(1, 2, _round),
    "len": _Builtin(1, 1, lambda args: float(len(require_string(args[0])))),
    "upper": _Builtin(1, 1, lambda args: require_string(args[0]).upper()),
    "lower": _Builtin(1, 1, lambda args: require_string(args[0]).lower()),
    "str": _Builtin(1, 1, lambda args: value_text(args[0])),
    "num": _Builtin(1, 1, _num),
    "if": _Builtin(3, 3, None),
}


def get_builtin(name: str, count: int) -> _Builtin:
    builtin = _BUILTINS.get(name)
    if builtin is None:
        raise EvalError(f"undefined function: {name}")
    builtin.check_arity(name, count)
    return builtin


def call_builtin(builtin: _Builtin, arguments: list[Value]) -> Value:
    assert builtin.function is not None
    try:
        return builtin.function(arguments)
    except (OverflowError, ValueError) as error:
        raise EvalError(str(error)) from error
