import math
from minilang.errors import EvalError


def _check_arity(name: str, expected: int | tuple, actual: int):
    """Check arity and raise EvalError if wrong."""
    if isinstance(expected, int):
        if actual != expected:
            n_text = str(expected)
            raise EvalError(f"{name}() takes {n_text} argument(s), got {actual}")
    elif isinstance(expected, tuple):
        if actual not in expected:
            expected_list = sorted(expected)
            raise EvalError(
                f"{name}() takes {expected_list[0]} argument(s), got {actual}"
                if len(expected_list) == 1
                else f"{name}() takes {expected_list[0]} argument(s), got {actual}"
            )


def _to_formatted_number(x: float) -> str:
    """Format a number using the same rules as the REPL."""
    if x == float("inf") or x == float("-inf") or x != x:
        # Handle special cases
        r = repr(x)
        return r
    if x == int(x) and abs(x) < 2**53:
        return str(int(x))
    s = repr(x)
    # Remove trailing zeros and possible trailing dot
    if "." in s:
        s = s.rstrip("0")
        if s.endswith("."):
            s = s[:-1]
    return s


def builtin_abs(args: list) -> float:
    _check_arity("abs", 1, len(args))
    x = args[0]
    if not isinstance(x, (int, float)):
        raise EvalError(f"abs() requires a number, got {type(x).__name__}")
    return abs(x)


def builtin_min(args: list) -> float:
    if len(args) < 1:
        raise EvalError(f"min() takes 1 argument(s), got 0")
    for x in args:
        if not isinstance(x, (int, float)):
            raise EvalError(f"min() requires numbers")
    return min(args)


def builtin_max(args: list) -> float:
    if len(args) < 1:
        raise EvalError(f"max() takes 1 argument(s), got 0")
    for x in args:
        if not isinstance(x, (int, float)):
            raise EvalError(f"max() requires numbers")
    return max(args)


def builtin_round(args: list) -> float:
    x = args[0]
    if not isinstance(x, (int, float)):
        raise EvalError(f"round() requires a number")
    if len(args) == 1:
        return round(x)
    elif len(args) == 2:
        n = args[1]
        if not isinstance(n, (int, float)):
            raise EvalError(f"round() requires a number for n")
        if n != int(n):
            raise EvalError(f"round() requires an integer for n")
        return round(x, int(n))
    else:
        _check_arity("round", 1, len(args))


def builtin_len(args: list) -> float:
    _check_arity("len", 1, len(args))
    x = args[0]
    if not isinstance(x, str):
        raise EvalError(f"len() requires a string")
    return float(len(x))


def builtin_upper(args: list) -> str:
    _check_arity("upper", 1, len(args))
    x = args[0]
    if not isinstance(x, str):
        raise EvalError(f"upper() requires a string")
    return x.upper()


def builtin_lower(args: list) -> str:
    _check_arity("lower", 1, len(args))
    x = args[0]
    if not isinstance(x, str):
        raise EvalError(f"lower() requires a string")
    return x.lower()


def builtin_str_func(args: list) -> str:
    _check_arity("str", 1, len(args))
    x = args[0]
    if isinstance(x, bool):
        return "true" if x else "false"
    if isinstance(x, float):
        return _to_formatted_number(x)
    if isinstance(x, str):
        return x
    raise EvalError(f"str() received unsupported type")


def builtin_num(args: list) -> float:
    _check_arity("num", 1, len(args))
    x = args[0]
    if not isinstance(x, str):
        raise EvalError(f"num() requires a string")
    s = x.strip()
    try:
        return float(s)
    except ValueError:
        raise EvalError(f"cannot parse {s!r} as number")


def _if_thunk(args_evaluated: list, cond_idx: int, then_idx: int, else_idx: int, position: int | None):
    """Handle lazy evaluation for if()."""
    from minilang.evaluator import _eval_node
    cond = args_evaluated[0]
    if not isinstance(cond, bool):
        raise EvalError("if() condition must be a boolean", position)
    if cond:
        return True, then_idx
    else:
        return False, else_idx


# Registry of built-in functions
BUILTINS = {
    "abs": builtin_abs,
    "min": builtin_min,
    "max": builtin_max,
    "round": builtin_round,
    "len": builtin_len,
    "upper": builtin_upper,
    "lower": builtin_lower,
    "str": builtin_str_func,
    "num": builtin_num,
}