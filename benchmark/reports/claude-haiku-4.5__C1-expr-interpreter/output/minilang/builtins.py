from .errors import EvalError


def builtin_abs(x: float) -> float:
    """Return absolute value of x."""
    return abs(x)


def builtin_min(*args: float) -> float:
    """Return minimum of arguments."""
    if not args:
        raise EvalError("min() takes 1 argument(s) or more, got 0")
    return min(args)


def builtin_max(*args: float) -> float:
    """Return maximum of arguments."""
    if not args:
        raise EvalError("max() takes 1 argument(s) or more, got 0")
    return max(args)


def builtin_round(x: float, n: float | None = None) -> float:
    """Round x to n decimal places (default 0)."""
    if n is None:
        return float(round(x))
    n_int = int(n)
    if n != n_int:
        raise EvalError("round() n argument must be a whole number")
    return float(round(x, n_int))


def builtin_len(s: str) -> float:
    """Return length of string."""
    return float(len(s))


def builtin_upper(s: str) -> str:
    """Return uppercase version of string."""
    return s.upper()


def builtin_lower(s: str) -> str:
    """Return lowercase version of string."""
    return s.lower()


def builtin_str(value: object) -> str:
    """Convert value to string."""
    if isinstance(value, bool):
        return "true" if value else "false"
    elif isinstance(value, float):
        if value == int(value):
            return str(int(value))
        return repr(value)
    else:
        return value


def builtin_num(s: str) -> float:
    """Convert string to number."""
    try:
        s_stripped = s.strip()
        return float(s_stripped)
    except ValueError:
        raise EvalError(f"cannot parse '{s}' as a number")


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
}
