"""MiniLang built-in functions."""

import math
from typing import Any
from .errors import EvalError


def format_number(val: float) -> str:
    """Format a float according to MiniLang rules (rule 33)."""
    if val.is_integer():
        return str(int(val))
    return repr(val)


def builtin_abs(args: list[Any], position: int | None = None) -> float:
    if len(args) != 1:
        raise EvalError(f"abs() takes 1 argument(s), got {len(args)}", position=position)
    x = args[0]
    if type(x) is not float:
        raise EvalError(f"abs() argument must be a number, got {type(x).__name__}", position=position)
    return float(abs(x))


def builtin_min(args: list[Any], position: int | None = None) -> float:
    if len(args) < 1:
        raise EvalError(f"min() takes at least 1 argument(s), got {len(args)}", position=position)
    for arg in args:
        if type(arg) is not float:
            raise EvalError(f"min() arguments must be numbers, got {type(arg).__name__}", position=position)
    return float(min(args))


def builtin_max(args: list[Any], position: int | None = None) -> float:
    if len(args) < 1:
        raise EvalError(f"max() takes at least 1 argument(s), got {len(args)}", position=position)
    for arg in args:
        if type(arg) is not float:
            raise EvalError(f"max() arguments must be numbers, got {type(arg).__name__}", position=position)
    return float(max(args))


def builtin_round(args: list[Any], position: int | None = None) -> float:
    if len(args) not in (1, 2):
        raise EvalError(f"round() takes 1 or 2 argument(s), got {len(args)}", position=position)
    x = args[0]
    if type(x) is not float:
        raise EvalError(f"round() first argument must be a number, got {type(x).__name__}", position=position)
    if len(args) == 1:
        return float(round(x))
    n = args[1]
    if type(n) is not float or not n.is_integer():
        raise EvalError("round() second argument must be a whole number", position=position)
    return float(round(x, int(n)))


def builtin_len(args: list[Any], position: int | None = None) -> float:
    if len(args) != 1:
        raise EvalError(f"len() takes 1 argument(s), got {len(args)}", position=position)
    s = args[0]
    if type(s) is not str:
        raise EvalError(f"len() argument must be a string, got {type(s).__name__}", position=position)
    return float(len(s))


def builtin_upper(args: list[Any], position: int | None = None) -> str:
    if len(args) != 1:
        raise EvalError(f"upper() takes 1 argument(s), got {len(args)}", position=position)
    s = args[0]
    if type(s) is not str:
        raise EvalError(f"upper() argument must be a string, got {type(s).__name__}", position=position)
    return s.upper()


def builtin_lower(args: list[Any], position: int | None = None) -> str:
    if len(args) != 1:
        raise EvalError(f"lower() takes 1 argument(s), got {len(args)}", position=position)
    s = args[0]
    if type(s) is not str:
        raise EvalError(f"lower() argument must be a string, got {type(s).__name__}", position=position)
    return s.lower()


def builtin_str(args: list[Any], position: int | None = None) -> str:
    if len(args) != 1:
        raise EvalError(f"str() takes 1 argument(s), got {len(args)}", position=position)
    x = args[0]
    if type(x) is bool:
        return "true" if x else "false"
    elif type(x) is float:
        return format_number(x)
    elif type(x) is str:
        return x
    else:
        raise EvalError(f"unsupported value for str(): {x!r}", position=position)


def builtin_num(args: list[Any], position: int | None = None) -> float:
    if len(args) != 1:
        raise EvalError(f"num() takes 1 argument(s), got {len(args)}", position=position)
    s = args[0]
    if type(s) is not str:
        raise EvalError(f"num() argument must be a string, got {type(s).__name__}", position=position)
    try:
        val = float(s)
        if math.isnan(val) or math.isinf(val):
            raise ValueError()
        return val
    except ValueError:
        raise EvalError(f"cannot convert {s!r} to number", position=position)


EAGER_BUILTINS = {
    "abs": builtin_abs,
    "min": builtin_min,
    "max": builtin_max,
    "round": builtin_round,
    "len": builtin_len,
    "upper": builtin_upper,
    "lower": builtin_lower,
    "str": builtin_str,
    "num": builtin_num,
}

ALL_BUILTINS = set(EAGER_BUILTINS.keys()) | {"if"}
