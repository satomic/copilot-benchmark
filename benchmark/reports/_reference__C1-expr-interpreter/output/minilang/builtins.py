"""Built-in functions and value formatting."""

from __future__ import annotations

from .errors import EvalError

# name -> allowed argument counts; None means "one or more"
ARITY: dict[str, tuple[int, ...] | None] = {
    "abs": (1,),
    "min": None,
    "max": None,
    "round": (1, 2),
    "len": (1,),
    "upper": (1,),
    "lower": (1,),
    "str": (1,),
    "num": (1,),
    "if": (3,),
}

# Functions whose arguments must NOT be evaluated eagerly.
LAZY = frozenset({"if"})

_ESCAPES = {
    chr(92): chr(92) * 2,          # backslash    -> \\
    '"': chr(92) + '"',            # double quote -> \"
    "\n": chr(92) + "n",           # newline      -> \n
    "\t": chr(92) + "t",           # tab          -> \t
    "\r": chr(92) + "r",           # CR           -> \r
}


def is_builtin(name: str) -> bool:
    return name in ARITY


def check_arity(name: str, count: int) -> None:
    allowed = ARITY[name]
    if allowed is None:
        if count < 1:
            raise EvalError(f"{name}() takes at least 1 argument(s), got {count}")
        return
    if count not in allowed:
        expected = " or ".join(str(n) for n in allowed)
        raise EvalError(f"{name}() takes {expected} argument(s), got {count}")


def call(name: str, args: list) -> object:
    """Invoke a strict (non-lazy) built-in with already-evaluated arguments."""
    check_arity(name, len(args))

    if name == "abs":
        return abs(_number(name, args[0]))
    if name == "min":
        return min(_number(name, value) for value in args)
    if name == "max":
        return max(_number(name, value) for value in args)
    if name == "round":
        value = _number(name, args[0])
        if len(args) == 1:
            return float(round(value))
        digits = _number(name, args[1])
        if not digits.is_integer():
            raise EvalError(f"round() digits must be a whole number, got {digits!r}")
        return float(round(value, int(digits)))
    if name == "len":
        return float(len(_string(name, args[0])))
    if name == "upper":
        return _string(name, args[0]).upper()
    if name == "lower":
        return _string(name, args[0]).lower()
    if name == "str":
        return format_value(args[0], quote_strings=False)
    if name == "num":
        text = _string(name, args[0])
        try:
            return float(text.strip())
        except ValueError:
            raise EvalError(f"num() cannot parse {text!r}") from None

    raise EvalError(f"undefined function: {name}")


def format_number(value: float) -> str:
    """Render a number without a trailing '.0' when it is integral."""
    if value != value or value in (float("inf"), float("-inf")):
        return repr(value)
    if value.is_integer():
        return str(int(value))
    return repr(value)


def format_value(value: object, *, quote_strings: bool = True) -> str:
    """Render a minilang value for display."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        return format_number(value)
    if isinstance(value, str):
        if not quote_strings:
            return value
        body = "".join(_ESCAPES.get(char, char) for char in value)
        return '"' + body + '"'
    raise EvalError(f"cannot format value {value!r}")


def _number(name: str, value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, float):
        raise EvalError(f"{name}() expects a number, got {_type_name(value)}")
    return value


def _string(name: str, value: object) -> str:
    if not isinstance(value, str):
        raise EvalError(f"{name}() expects a string, got {_type_name(value)}")
    return value


def _type_name(value: object) -> str:
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    return type(value).__name__
