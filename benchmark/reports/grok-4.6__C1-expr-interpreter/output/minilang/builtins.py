import math

from minilang.errors import EvalError, LexError
from minilang.lexer import tokenize


def _is_number(value) -> bool:
    return isinstance(value, float) and not isinstance(value, bool)


def _arity_exact(name: str, args: list, expected: int):
    n = len(args)
    if n != expected:
        raise EvalError(f"{name}() takes {expected} argument(s), got {n}")


def _arity_min(name: str, args: list, minimum: int):
    n = len(args)
    if n < minimum:
        raise EvalError(f"{name}() takes at least {minimum} argument(s), got {n}")


def _require_number(name: str, value, label="argument"):
    if not _is_number(value):
        raise EvalError(f"{name}() {label} must be a number")


def format_number(value: float) -> str:
    if math.isfinite(value) and value.is_integer():
        return str(int(value))
    return repr(value)


def format_value(value) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        return format_number(value)
    if isinstance(value, str):
        escaped = (
            value.replace("\\", "\\\\")
            .replace("\n", "\\n")
            .replace("\t", "\\t")
            .replace("\r", "\\r")
            .replace('"', '\\"')
        )
        return f'"{escaped}"'
    raise EvalError(f"unsupported value: {value!r}")


def builtin_abs(args):
    _arity_exact("abs", args, 1)
    _require_number("abs", args[0])
    return abs(args[0])


def builtin_min(args):
    _arity_min("min", args, 1)
    for a in args:
        _require_number("min", a)
    return min(args)


def builtin_max(args):
    _arity_min("max", args, 1)
    for a in args:
        _require_number("max", a)
    return max(args)


def builtin_round(args):
    n = len(args)
    if n not in (1, 2):
        raise EvalError(f"round() takes 1 or 2 argument(s), got {n}")
    _require_number("round", args[0])
    if n == 1:
        return float(round(args[0]))
    _require_number("round", args[1], "ndigits")
    ndigits = args[1]
    if not ndigits.is_integer():
        raise EvalError("round() ndigits must be a whole number")
    return float(round(args[0], int(ndigits)))


def builtin_len(args):
    _arity_exact("len", args, 1)
    if not isinstance(args[0], str):
        raise EvalError("len() argument must be a string")
    return float(len(args[0]))


def builtin_upper(args):
    _arity_exact("upper", args, 1)
    if not isinstance(args[0], str):
        raise EvalError("upper() argument must be a string")
    return args[0].upper()


def builtin_lower(args):
    _arity_exact("lower", args, 1)
    if not isinstance(args[0], str):
        raise EvalError("lower() argument must be a string")
    return args[0].lower()


def builtin_str(args):
    _arity_exact("str", args, 1)
    value = args[0]
    if isinstance(value, bool):
        return "true" if value else "false"
    if _is_number(value):
        return format_number(value)
    if isinstance(value, str):
        return value
    raise EvalError("str() argument must be a number, string, or boolean")


def builtin_num(args):
    _arity_exact("num", args, 1)
    if not isinstance(args[0], str):
        raise EvalError("num() argument must be a string")
    # Interpret using minilang number tokens so "1." and junk are rejected.
    try:
        tokens = tokenize(args[0])
    except LexError:
        raise EvalError("cannot parse number") from None
    if len(tokens) != 1 or tokens[0].kind != "NUMBER":
        raise EvalError("cannot parse number")
    return tokens[0].value


FUNCTIONS = {
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
