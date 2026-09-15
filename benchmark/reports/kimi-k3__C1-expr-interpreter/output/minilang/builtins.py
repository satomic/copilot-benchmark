"""Built-in functions for minilang.

Each built-in takes a list of already-evaluated arguments and raises
EvalError on arity or type violations. ``if`` is intentionally absent:
it is lazy and therefore handled directly by the evaluator.
"""

from .errors import EvalError


def format_number(value):
    """REPL/rule-33 number formatting: integral floats print with no
    decimal part, everything else uses repr's shortest form."""
    if value.is_integer():
        return str(int(value))
    return repr(value)


def typename(value):
    if type(value) is bool:
        return "boolean"
    if type(value) is float:
        return "number"
    return "string"


def _arity(name, args, expected):
    if len(args) != expected:
        raise EvalError(f"{name}() takes {expected} argument(s), got {len(args)}")


def _number(name, value):
    if type(value) is not float:
        raise EvalError(f"{name}() expects a number, got {typename(value)}")
    return value


def _string(name, value):
    if type(value) is not str:
        raise EvalError(f"{name}() expects a string, got {typename(value)}")
    return value


def _builtin_abs(args):
    _arity("abs", args, 1)
    return abs(_number("abs", args[0]))


def _minmax(name, args, op):
    # Interpretation choice: variadic built-ins report "at least 1".
    if len(args) < 1:
        raise EvalError(f"{name}() takes at least 1 argument(s), got {len(args)}")
    for value in args:
        _number(name, value)
    return float(op(args))


def _builtin_min(args):
    return _minmax("min", args, min)


def _builtin_max(args):
    return _minmax("max", args, max)


def _builtin_round(args):
    # Interpretation choice: round accepts 1 or 2 arguments.
    if len(args) not in (1, 2):
        raise EvalError(f"round() takes 1 or 2 argument(s), got {len(args)}")
    x = _number("round", args[0])
    if len(args) == 1:
        return float(round(x))
    n = _number("round", args[1])
    if not n.is_integer():
        raise EvalError("round() argument 2 must be a whole number")
    return float(round(x, int(n)))


def _builtin_len(args):
    _arity("len", args, 1)
    return float(len(_string("len", args[0])))


def _builtin_upper(args):
    _arity("upper", args, 1)
    return _string("upper", args[0]).upper()


def _builtin_lower(args):
    _arity("lower", args, 1)
    return _string("lower", args[0]).lower()


def _builtin_str(args):
    _arity("str", args, 1)
    value = args[0]
    if type(value) is bool:
        return "true" if value else "false"
    if type(value) is float:
        return format_number(value)
    return value


def _builtin_num(args):
    _arity("num", args, 1)
    text = _string("num", args[0])
    try:
        return float(text)
    except ValueError:
        raise EvalError(f"num() cannot parse {text!r} as a number") from None


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
