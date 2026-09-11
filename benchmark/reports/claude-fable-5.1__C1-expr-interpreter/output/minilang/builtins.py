"""Built-in functions and value formatting for minilang."""

import math

from .errors import EvalError


# -- formatting -------------------------------------------------------------

def type_name(value: object) -> str:
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    return type(value).__name__


def format_number(value: float) -> str:
    if math.isfinite(value) and value.is_integer():
        return str(int(value))
    return repr(value)


_REESCAPE = {"\\": "\\\\", '"': '\\"', "\n": "\\n", "\t": "\\t", "\r": "\\r"}


def format_value(value: object, quote_strings: bool = True) -> str:
    """Render a value the way the REPL does.

    ``str()`` in minilang uses ``quote_strings=False`` so strings pass through unchanged.
    """
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        return format_number(value)
    if isinstance(value, str):
        if not quote_strings:
            return value
        return '"' + "".join(_REESCAPE.get(ch, ch) for ch in value) + '"'
    raise EvalError(f"unsupported value: {value!r}")


# -- argument checking ---------------------------------------------------------

def _check_arity(name: str, args: list, expected: int) -> None:
    if len(args) != expected:
        raise EvalError(f"{name}() takes {expected} argument(s), got {len(args)}")


def _check_number(name: str, value: object) -> float:
    if type(value) is not float:
        raise EvalError(f"{name}() expects a number, got {type_name(value)}")
    return value


def _check_string(name: str, value: object) -> str:
    if type(value) is not str:
        raise EvalError(f"{name}() expects a string, got {type_name(value)}")
    return value


# -- strict builtins (arguments already evaluated) ----------------------------

def _abs(args: list) -> float:
    _check_arity("abs", args, 1)
    return abs(_check_number("abs", args[0]))


def _min(args: list) -> float:
    if not args:
        raise EvalError("min() takes at least 1 argument(s), got 0")
    return min(_check_number("min", a) for a in args)


def _max(args: list) -> float:
    if not args:
        raise EvalError("max() takes at least 1 argument(s), got 0")
    return max(_check_number("max", a) for a in args)


def _round(args: list) -> float:
    if len(args) not in (1, 2):
        raise EvalError(f"round() takes 1 or 2 argument(s), got {len(args)}")
    x = _check_number("round", args[0])
    if len(args) == 1:
        if not math.isfinite(x):
            raise EvalError("round() cannot round a non-finite number")
        return float(round(x))
    n = _check_number("round", args[1])
    if not n.is_integer():
        raise EvalError(f"round() expects a whole number of digits, got {format_number(n)}")
    return float(round(x, int(n)))


def _len(args: list) -> float:
    _check_arity("len", args, 1)
    return float(len(_check_string("len", args[0])))


def _upper(args: list) -> str:
    _check_arity("upper", args, 1)
    return _check_string("upper", args[0]).upper()


def _lower(args: list) -> str:
    _check_arity("lower", args, 1)
    return _check_string("lower", args[0]).lower()


def _str(args: list) -> str:
    _check_arity("str", args, 1)
    return format_value(args[0], quote_strings=False)


def _num(args: list) -> float:
    _check_arity("num", args, 1)
    s = _check_string("num", args[0])
    # Reject forms Python's float() accepts but minilang does not (underscores,
    # inf/nan); everything else is delegated to float().
    stripped = s.strip()
    if "_" in stripped or not any(c.isdigit() for c in stripped):
        raise EvalError(f"num() cannot parse {s!r}")
    try:
        return float(stripped)
    except ValueError:
        raise EvalError(f"num() cannot parse {s!r}") from None


BUILTINS = {
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


# -- lazy builtins (receive unevaluated argument nodes) ----------------------

def _if(arg_nodes: tuple, evaluate_node) -> object:
    if len(arg_nodes) != 3:
        raise EvalError(f"if() takes 3 argument(s), got {len(arg_nodes)}")
    cond = evaluate_node(arg_nodes[0])
    if type(cond) is not bool:
        raise EvalError(f"if() expects a boolean condition, got {type_name(cond)}")
    return evaluate_node(arg_nodes[1] if cond else arg_nodes[2])


LAZY_BUILTINS = {
    "if": _if,
}
