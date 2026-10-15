"""Built-in functions and value formatting for minilang."""

import math
import re

from .errors import EvalError

# name -> (min_args, max_args); max_args None means variadic.
ARITY = {
    "abs": (1, 1),
    "min": (1, None),
    "max": (1, None),
    "round": (1, 2),
    "len": (1, 1),
    "upper": (1, 1),
    "lower": (1, 1),
    "str": (1, 1),
    "num": (1, 1),
    "if": (3, 3),  # special-cased by the evaluator so that only the taken branch runs
}

_NUM_RE = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]+)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?")


def type_name(value):
    if type(value) is bool:
        return "boolean"
    if type(value) is float:
        return "number"
    return "string"


def format_value(value):
    """REPL/str() rendering: integral numbers without decimals, booleans as true/false,
    strings quoted with escapes re-encoded."""
    if type(value) is bool:
        return "true" if value else "false"
    if type(value) is float:
        if value.is_integer():
            return str(int(value))
        return repr(value)
    escaped = (
        value.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\t", "\\t")
        .replace("\r", "\\r")
    )
    return f'"{escaped}"'


def check_arity(name, count):
    lo, hi = ARITY[name]
    if hi is None:
        expected = f"at least {lo} argument(s)"
    elif lo == hi:
        expected = f"{lo} argument(s)"
    else:
        expected = f"{lo} or {hi} argument(s)"
    if count < lo or (hi is not None and count > hi):
        raise EvalError(f"{name}() takes {expected}, got {count}")


def _need_num(name, value):
    if type(value) is not float:
        raise EvalError(f"{name}() expects a number, got {type_name(value)}")
    return value


def _need_str(name, value):
    if type(value) is not str:
        raise EvalError(f"{name}() expects a string, got {type_name(value)}")
    return value


def _abs(x):
    return abs(_need_num("abs", x))


def _min(*xs):
    return min(_need_num("min", x) for x in xs)


def _max(*xs):
    return max(_need_num("max", x) for x in xs)


def _round(x, n=None):
    _need_num("round", x)
    if n is None:
        try:
            return float(round(x))
        except (OverflowError, ValueError):
            raise EvalError("round() cannot round a non-finite number")
    _need_num("round", n)
    if not (math.isfinite(n) and n == int(n)):
        raise EvalError("round() precision must be a whole number")
    return float(round(x, int(n)))


def _len(s):
    return float(len(_need_str("len", s)))


def _upper(s):
    return _need_str("upper", s).upper()


def _lower(s):
    return _need_str("lower", s).lower()


def _str(x):
    if type(x) is str:
        return x
    return format_value(x)


def _num(s):
    text = _need_str("num", s).strip()
    if not _NUM_RE.fullmatch(text):
        raise EvalError(f"num(): cannot convert {s!r} to a number")
    return float(text)


# Eager builtins; ``if`` is handled by the evaluator.
FUNCTIONS = {
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
