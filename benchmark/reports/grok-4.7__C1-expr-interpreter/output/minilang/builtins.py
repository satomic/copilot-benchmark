"""Built-in functions and value formatting.

Ambiguous choices:
- ``str()`` on a string returns the string itself. REPL quoting is display-only.
- ``num()`` allows surrounding whitespace, an optional leading sign, and a
  number literal using the same grammar as the lexer (so ``"1."`` is rejected).
- ``round``'s second argument may be any finite whole number, including negatives.
- Variadic arity text uses ``at least 1`` and ``1 or 2`` inside the standard template.
"""

import math
import re

from minilang.errors import EvalError

# Same number grammar as the lexer, plus an optional sign.
_NUMBER_RE = re.compile(
    r"[+-]?(?:\d+\.\d+(?:[eE][+-]?\d+)?|\d+\.[eE][+-]?\d+"
    r"|\.\d+(?:[eE][+-]?\d+)?|\d+(?:[eE][+-]?\d+)?)\Z"
)


def format_number(value: float) -> str:
    """Integral numbers print without a decimal part; otherwise use ``repr``."""
    if math.isfinite(value) and value.is_integer():
        return str(int(value))
    return repr(value)


def escape_string(value: str) -> str:
    return (
        value.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\r", "\\r")
        .replace("\t", "\\t")
    )


def format_value(value) -> str:
    """Format a value the way the REPL prints it."""
    if type(value) is bool:
        return "true" if value else "false"
    if type(value) is float:
        return format_number(value)
    if type(value) is str:
        return '"' + escape_string(value) + '"'
    return repr(value)


def format_plain(value) -> str:
    """``str()`` conversion: numbers and booleans match display, strings do not quote."""
    if type(value) is bool:
        return "true" if value else "false"
    if type(value) is float:
        return format_number(value)
    if type(value) is str:
        return value
    raise EvalError(f"unsupported value: {value!r}")


def _arity(name: str, expected: str, got: int) -> None:
    raise EvalError(f"{name}() takes {expected} argument(s), got {got}")


def _require_number(name: str, value) -> float:
    if type(value) is not float:
        raise EvalError(f"{name}() expects a number")
    return value


def _require_string(name: str, value) -> str:
    if type(value) is not str:
        raise EvalError(f"{name}() expects a string")
    return value


def _builtin_abs(args: list):
    if len(args) != 1:
        _arity("abs", "1", len(args))
    return abs(_require_number("abs", args[0]))


def _builtin_min(args: list):
    if len(args) < 1:
        _arity("min", "at least 1", len(args))
    numbers = [_require_number("min", arg) for arg in args]
    return min(numbers)


def _builtin_max(args: list):
    if len(args) < 1:
        _arity("max", "at least 1", len(args))
    numbers = [_require_number("max", arg) for arg in args]
    return max(numbers)


def _builtin_round(args: list):
    if len(args) not in (1, 2):
        _arity("round", "1 or 2", len(args))
    number = _require_number("round", args[0])
    if len(args) == 1:
        return float(round(number))
    digits = _require_number("round", args[1])
    if not math.isfinite(digits) or not digits.is_integer():
        raise EvalError("round() second argument must be a whole number")
    try:
        return float(round(number, int(digits)))
    except (OverflowError, ValueError):
        raise EvalError("round() second argument must be a whole number") from None


def _builtin_len(args: list):
    if len(args) != 1:
        _arity("len", "1", len(args))
    return float(len(_require_string("len", args[0])))


def _builtin_upper(args: list):
    if len(args) != 1:
        _arity("upper", "1", len(args))
    return _require_string("upper", args[0]).upper()


def _builtin_lower(args: list):
    if len(args) != 1:
        _arity("lower", "1", len(args))
    return _require_string("lower", args[0]).lower()


def _builtin_str(args: list):
    if len(args) != 1:
        _arity("str", "1", len(args))
    return format_plain(args[0])


def _builtin_num(args: list):
    if len(args) != 1:
        _arity("num", "1", len(args))
    text = _require_string("num", args[0]).strip()
    if _NUMBER_RE.fullmatch(text) is None:
        raise EvalError(f"num() cannot parse {args[0]!r}")
    return float(text)


BUILTINS = {
    "abs": _builtin_abs,
    "min": _builtin_min,
    "max": _builtin_max,
    "round": _builtin_round,
    "len": _builtin_len,
    "upper": _builtin_upper,
    "lower": _builtin_lower,
    "str": _builtin_str,
    "num": _builtin_num,
}


def call_builtin(name: str, args: list):
    function = BUILTINS.get(name)
    if function is None:
        raise EvalError(f"undefined function: {name}")
    return function(args)
