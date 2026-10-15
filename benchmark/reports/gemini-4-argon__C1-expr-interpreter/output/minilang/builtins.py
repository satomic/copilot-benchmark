import math
import re
from typing import Callable
from .errors import EvalError

_NUM_RE = re.compile(r"^[+-]?(?:\d+(?:\.\d+)?|\.\d+)(?:[eE][+-]?\d+)?$")


def format_number(val: float) -> str:
    if val.is_integer():
        return str(int(val))
    return repr(val)


def format_repl_value(val: object) -> str:
    if type(val) is bool:
        return "true" if val else "false"
    if type(val) is float:
        return format_number(val)
    if type(val) is str:
        escaped = (
            val.replace("\\", "\\\\")
            .replace('"', '\\"')
            .replace("\n", "\\n")
            .replace("\r", "\\r")
            .replace("\t", "\\t")
        )
        return f'"{escaped}"'
    raise EvalError(f"unsupported value: {val!r}")


def _check_arity(name: str, expected: int, got: int) -> None:
    if got != expected:
        raise EvalError(f"{name}() takes {expected} argument(s), got {got}")


def _require_number(name: str, val: object) -> float:
    if type(val) is not float:
        raise EvalError(f"{name}() requires number argument(s)")
    return val


def _require_string(name: str, val: object) -> str:
    if type(val) is not str:
        raise EvalError(f"{name}() requires a string argument")
    return val


def _builtin_abs(args: list[object]) -> float:
    x = _require_number("abs", args[0])
    return float(abs(x))


def _builtin_min(args: list[object]) -> float:
    nums = [_require_number("min", a) for a in args]
    return float(min(nums))


def _builtin_max(args: list[object]) -> float:
    nums = [_require_number("max", a) for a in args]
    return float(max(nums))


def _builtin_round(args: list[object]) -> float:
    x = _require_number("round", args[0])
    if len(args) == 1:
        return float(round(x))
    n = _require_number("round", args[1])
    if not n.is_integer():
        raise EvalError("round() second argument must be a whole number")
    return float(round(x, int(n)))


def _builtin_len(args: list[object]) -> float:
    s = _require_string("len", args[0])
    return float(len(s))


def _builtin_upper(args: list[object]) -> str:
    s = _require_string("upper", args[0])
    return s.upper()


def _builtin_lower(args: list[object]) -> str:
    s = _require_string("lower", args[0])
    return s.lower()


def _builtin_str(args: list[object]) -> str:
    val = args[0]
    if type(val) is str:
        return val
    if type(val) is bool:
        return "true" if val else "false"
    if type(val) is float:
        return format_number(val)
    raise EvalError(f"unsupported value for str(): {val!r}")


def _builtin_num(args: list[object]) -> float:
    s = _require_string("num", args[0]).strip()
    if not _NUM_RE.match(s):
        raise EvalError(f"cannot convert {args[0]!r} to number")
    try:
        val = float(s)
    except ValueError as exc:
        raise EvalError(f"cannot convert {args[0]!r} to number") from exc
    if not math.isfinite(val):
        raise EvalError(f"cannot convert {args[0]!r} to number")
    return val


EAGER_BUILTINS: dict[str, tuple[int | str, Callable[[list[object]], object]]] = {
    "abs": (1, _builtin_abs),
    "min": ("1+", _builtin_min),
    "max": ("1+", _builtin_max),
    "round": ("1-2", _builtin_round),
    "len": (1, _builtin_len),
    "upper": (1, _builtin_upper),
    "lower": (1, _builtin_lower),
    "str": (1, _builtin_str),
    "num": (1, _builtin_num),
}


def call_builtin(
    name: str,
    raw_args: list[object],
    eval_fn: Callable[[object], object],
) -> object:
    got = len(raw_args)

    if name == "if":
        _check_arity("if", 3, got)
        cond = eval_fn(raw_args[0])
        if type(cond) is not bool:
            raise EvalError("if() condition must be a boolean")
        return eval_fn(raw_args[1]) if cond else eval_fn(raw_args[2])

    if name not in EAGER_BUILTINS:
        raise EvalError(f"undefined function: {name}")

    arity_spec, func = EAGER_BUILTINS[name]
    if isinstance(arity_spec, int):
        _check_arity(name, arity_spec, got)
    elif arity_spec == "1+":
        if got < 1:
            raise EvalError(f"{name}() takes at least 1 argument(s), got {got}")
    elif arity_spec == "1-2":
        if got not in (1, 2):
            raise EvalError(f"{name}() takes 1 or 2 argument(s), got {got}")

    evaluated_args = [eval_fn(arg) for arg in raw_args]
    return func(evaluated_args)
