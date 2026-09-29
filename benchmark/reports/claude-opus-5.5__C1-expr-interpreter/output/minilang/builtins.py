"""Built-in functions for minilang.

Every builtin receives a list of zero-argument thunks; calling a thunk evaluates
that argument. Eager builtins evaluate all arguments up front, while ``if``
evaluates only the condition and the taken branch.
"""

import re

from .errors import EvalError

# Accepted by num(): the minilang number syntax with an optional sign, surrounded by
# optional whitespace. Python-only spellings such as "inf", "nan" or "1_000" are rejected.
_NUM_RE = re.compile(r"[+-]?(?:\d+(?:\.\d+)?|\.\d+)(?:[eE][+-]?\d+)?")
_REESCAPE = {"\\": "\\\\", '"': '\\"', "\n": "\\n", "\t": "\\t", "\r": "\\r"}


def _type_name(value):
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    return type(value).__name__


def format_number(x: float) -> str:
    if x.is_integer():
        return str(int(x))
    return repr(x)


def format_value(value) -> str:
    """Format a value for REPL display (strings quoted and re-escaped)."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        return format_number(value)
    if isinstance(value, str):
        return '"' + "".join(_REESCAPE.get(c, c) for c in value) + '"'
    raise TypeError(f"not a minilang value: {value!r}")


def to_str(value) -> str:
    """Convert a value to a string as str() does (strings are returned unchanged)."""
    if isinstance(value, str):
        return value
    return format_value(value)


def _arity(name, thunks, expected):
    if len(thunks) != expected:
        raise EvalError(f"{name}() takes {expected} argument(s), got {len(thunks)}")


def _at_least(name, thunks, minimum):
    if len(thunks) < minimum:
        raise EvalError(f"{name}() takes at least {minimum} argument(s), got {len(thunks)}")


def _num(name, value):
    if not isinstance(value, float) or isinstance(value, bool):
        raise EvalError(f"{name}() expects a number, got {_type_name(value)}")
    return value


def _str(name, value):
    if not isinstance(value, str):
        raise EvalError(f"{name}() expects a string, got {_type_name(value)}")
    return value


def _abs(thunks):
    _arity("abs", thunks, 1)
    return abs(_num("abs", thunks[0]()))


def _min(thunks):
    _at_least("min", thunks, 1)
    return min(_num("min", t()) for t in thunks)


def _max(thunks):
    _at_least("max", thunks, 1)
    return max(_num("max", t()) for t in thunks)


def _round(thunks):
    if len(thunks) not in (1, 2):
        raise EvalError(f"round() takes 1 or 2 argument(s), got {len(thunks)}")
    x = _num("round", thunks[0]())
    try:
        if len(thunks) == 1:
            return float(round(x))
        n = _num("round", thunks[1]())
        if not n.is_integer():
            raise EvalError("round() precision must be a whole number")
        return float(round(x, int(n)))
    except (OverflowError, ValueError):
        raise EvalError(f"round() cannot round {format_number(x)}") from None


def _len(thunks):
    _arity("len", thunks, 1)
    return float(len(_str("len", thunks[0]())))


def _upper(thunks):
    _arity("upper", thunks, 1)
    return _str("upper", thunks[0]()).upper()


def _lower(thunks):
    _arity("lower", thunks, 1)
    return _str("lower", thunks[0]()).lower()


def _to_str(thunks):
    _arity("str", thunks, 1)
    return to_str(thunks[0]())


def _to_num(thunks):
    _arity("num", thunks, 1)
    s = _str("num", thunks[0]())
    text = s.strip()
    if not _NUM_RE.fullmatch(text):
        raise EvalError(f"num() cannot parse {s!r}")
    return float(text)


def _if(thunks):
    _arity("if", thunks, 3)
    cond = thunks[0]()
    if not isinstance(cond, bool):
        raise EvalError(f"if() condition must be a boolean, got {_type_name(cond)}")
    return thunks[1]() if cond else thunks[2]()


BUILTINS = {
    "abs": _abs,
    "min": _min,
    "max": _max,
    "round": _round,
    "len": _len,
    "upper": _upper,
    "lower": _lower,
    "str": _to_str,
    "num": _to_num,
    "if": _if,
}
