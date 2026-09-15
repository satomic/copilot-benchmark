import math

from .errors import EvalError


def _arity_error(name: str, expected: int, got: int) -> EvalError:
    return EvalError(f"{name}() takes {expected} argument(s), got {got}")


def _require_number(value, name: str):
    if type(value) is not float:
        raise EvalError(f"{name}() requires numbers")
    return value


def _require_string(value, name: str):
    if type(value) is not str:
        raise EvalError(f"{name}() requires strings")
    return value


def builtin_abs(args):
    if len(args) != 1:
        raise _arity_error("abs", 1, len(args))
    value = _require_number(args[0], "abs")
    return abs(value)


def builtin_min(args):
    if not args:
        raise _arity_error("min", 1, 0)
    values = [_require_number(v, "min") for v in args]
    return min(values)


def builtin_max(args):
    if not args:
        raise _arity_error("max", 1, 0)
    values = [_require_number(v, "max") for v in args]
    return max(values)


def builtin_round(args):
    if len(args) not in (1, 2):
        expected = 1 if len(args) < 2 else 2
        raise _arity_error("round", expected, len(args))
    x = _require_number(args[0], "round")
    if len(args) == 1:
        return float(round(x))
    n = _require_number(args[1], "round")
    if not n.is_integer():
        raise EvalError("round() requires a whole number for the second argument")
    return float(round(x, int(n)))


def builtin_len(args):
    if len(args) != 1:
        raise _arity_error("len", 1, len(args))
    value = _require_string(args[0], "len")
    return float(len(value))


def builtin_upper(args):
    if len(args) != 1:
        raise _arity_error("upper", 1, len(args))
    value = _require_string(args[0], "upper")
    return value.upper()


def builtin_lower(args):
    if len(args) != 1:
        raise _arity_error("lower", 1, len(args))
    value = _require_string(args[0], "lower")
    return value.lower()


def builtin_str(args):
    if len(args) != 1:
        raise _arity_error("str", 1, len(args))
    return format_value(args[0])


def builtin_num(args):
    if len(args) != 1:
        raise _arity_error("num", 1, len(args))
    value = _require_string(args[0], "num")
    try:
        return float(value.strip())
    except ValueError as exc:
        raise EvalError(f"invalid number: {value!r}") from exc


def builtin_if(args):
    if len(args) != 3:
        raise _arity_error("if", 3, len(args))
    if type(args[0]) is not bool:
        raise EvalError("if() requires a boolean condition")
    return args[1] if args[0] else args[2]


def format_value(value):
    if type(value) is bool:
        return "true" if value else "false"
    if type(value) is float:
        if value.is_integer():
            return str(int(value))
        return repr(value)
    if type(value) is str:
        escaped = value.replace("\\", "\\\\").replace('"', '\\"')
        escaped = escaped.replace("\n", "\\n").replace("\r", "\\r").replace("\t", "\\t")
        return f'"{escaped}"'
    raise TypeError(f"unsupported value: {value!r}")


BUILTINS = {
    "abs": builtin_abs,
    "min": builtin_min,
    "max": builtin_max,
    "round": builtin_round,
    "len": builtin_len,
    "upper": builtin_upper,
    "lower": builtin_lower,
    "str": builtin_str,
    "num": builtin_num,
    "if": builtin_if,
}
