import re

from .errors import EvalError

_NUM_RE = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?", re.ASCII)
_ESC_OUT = {"\n": "\\n", "\t": "\\t", "\r": "\\r", '"': '\\"', "\\": "\\\\"}


def format_number(x):
    if x.is_integer():
        return str(int(x))
    return repr(x)


def format_value(v):
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, float):
        return format_number(v)
    if isinstance(v, str):
        return '"' + "".join(_ESC_OUT.get(c, c) for c in v) + '"'
    return repr(v)


def _is_num(v):
    return isinstance(v, float)


def _arity(name, args, expected):
    if len(args) != expected:
        raise EvalError(f"{name}() takes {expected} argument(s), got {len(args)}")


def _need(name, v, kind):
    ok = _is_num(v) if kind == "number" else isinstance(v, str)
    if not ok:
        raise EvalError(f"{name}() expects a {kind} argument")


def _abs(*args):
    _arity("abs", args, 1)
    _need("abs", args[0], "number")
    return abs(args[0])


def _extreme(name, fn):
    def f(*args):
        if not args:
            raise EvalError(f"{name}() takes at least 1 argument(s), got 0")
        for a in args:
            _need(name, a, "number")
        return fn(args)
    return f


def _round(*args):
    if len(args) not in (1, 2):
        raise EvalError(f"round() takes 1 or 2 argument(s), got {len(args)}")
    _need("round", args[0], "number")
    if len(args) == 2:
        _need("round", args[1], "number")
        if not args[1].is_integer():
            raise EvalError("round() digits must be a whole number")
    try:
        if len(args) == 1:
            return float(round(args[0]))
        return float(round(args[0], int(args[1])))
    except (OverflowError, ValueError):
        raise EvalError("round() cannot round this value")


def _len(*args):
    _arity("len", args, 1)
    _need("len", args[0], "string")
    return float(len(args[0]))


def _upper(*args):
    _arity("upper", args, 1)
    _need("upper", args[0], "string")
    return args[0].upper()


def _lower(*args):
    _arity("lower", args, 1)
    _need("lower", args[0], "string")
    return args[0].lower()


def _str(*args):
    _arity("str", args, 1)
    v = args[0]
    if isinstance(v, str):
        return v
    if isinstance(v, bool):
        return "true" if v else "false"
    return format_number(v)


def _num(*args):
    _arity("num", args, 1)
    _need("num", args[0], "string")
    s = args[0].strip()
    if not _NUM_RE.fullmatch(s):
        raise EvalError(f"num() cannot parse {args[0]!r}")
    return float(s)


BUILTINS = {
    "abs": _abs,
    "min": _extreme("min", min),
    "max": _extreme("max", max),
    "round": _round,
    "len": _len,
    "upper": _upper,
    "lower": _lower,
    "str": _str,
    "num": _num,
}
# `if` is lazy, so the evaluator handles it directly.
LAZY_BUILTINS = {"if"}
