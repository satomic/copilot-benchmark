"""Built-in functions for minilang.

Each entry in BUILTINS is a callable that receives a list of already
evaluated arguments and returns a minilang value (float/str/bool), raising
EvalError on arity or type violations. ``if`` is handled specially in the
evaluator because its arguments must be evaluated lazily.
"""

from .errors import EvalError
from .evaluator import format_number


def _arity_error(name, expected, got):
    raise EvalError(f"{name}() takes {expected} argument(s), got {got}")


def _check_number(name, value, index=None):
    if not isinstance(value, float):
        where = f" (argument {index})" if index is not None else ""
        raise EvalError(f"{name}(){where} requires a number")


def _check_string(name, value, index=None):
    if not isinstance(value, str):
        where = f" (argument {index})" if index is not None else ""
        raise EvalError(f"{name}(){where} requires a string")


def _builtin_abs(args):
    if len(args) != 1:
        _arity_error("abs", 1, len(args))
    _check_number("abs", args[0])
    return abs(args[0])


def _builtin_min(args):
    if len(args) < 1:
        raise EvalError(f"min() takes at least 1 argument(s), got {len(args)}")
    for a in args:
        _check_number("min", a)
    return min(args)


def _builtin_max(args):
    if len(args) < 1:
        raise EvalError(f"max() takes at least 1 argument(s), got {len(args)}")
    for a in args:
        _check_number("max", a)
    return max(args)


def _builtin_round(args):
    if len(args) == 1:
        _check_number("round", args[0])
        return float(round(args[0]))
    if len(args) == 2:
        _check_number("round", args[0])
        n = args[1]
        _check_number("round", n)
        if n != int(n):
            raise EvalError("round() second argument must be a whole number")
        return float(round(args[0], int(n)))
    raise EvalError(f"round() takes 1 or 2 argument(s), got {len(args)}")


def _builtin_len(args):
    if len(args) != 1:
        _arity_error("len", 1, len(args))
    _check_string("len", args[0])
    return float(len(args[0]))


def _builtin_upper(args):
    if len(args) != 1:
        _arity_error("upper", 1, len(args))
    _check_string("upper", args[0])
    return args[0].upper()


def _builtin_lower(args):
    if len(args) != 1:
        _arity_error("lower", 1, len(args))
    _check_string("lower", args[0])
    return args[0].lower()


def _builtin_str(args):
    if len(args) != 1:
        _arity_error("str", 1, len(args))
    v = args[0]
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, float):
        return format_number(v)
    if isinstance(v, str):
        return v
    raise EvalError(f"str() cannot format value: {v!r}")


def _builtin_num(args):
    if len(args) != 1:
        _arity_error("num", 1, len(args))
    _check_string("num", args[0])
    try:
        return float(args[0].strip())
    except ValueError:
        raise EvalError(f"num() cannot parse value: {args[0]!r}")


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
