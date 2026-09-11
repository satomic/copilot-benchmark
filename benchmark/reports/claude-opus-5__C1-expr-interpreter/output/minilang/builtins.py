"""Built-in functions and value formatting for minilang."""

import math

from .errors import EvalError


def is_number(value):
    """True for minilang numbers (``bool`` is deliberately excluded)."""
    return isinstance(value, float) and not isinstance(value, bool)


def is_string(value):
    return isinstance(value, str)


def is_boolean(value):
    return isinstance(value, bool)


def is_value(value):
    return is_boolean(value) or is_number(value) or is_string(value)


def format_number(value):
    """Format a minilang number the way the REPL does (rule 33)."""
    if math.isfinite(value) and value.is_integer():
        return str(int(value))
    return repr(value)


def escape_string(value):
    """Re-escape a string's contents (without surrounding quotes)."""
    out = []
    for ch in value:
        if ch == "\\":
            out.append("\\\\")
        elif ch == '"':
            out.append('\\"')
        elif ch == "\n":
            out.append("\\n")
        elif ch == "\t":
            out.append("\\t")
        elif ch == "\r":
            out.append("\\r")
        else:
            out.append(ch)
    return "".join(out)


def format_value(value):
    """Format any minilang value for display (REPL and ``:vars``)."""
    if is_boolean(value):
        return "true" if value else "false"
    if is_number(value):
        return format_number(value)
    if is_string(value):
        return '"' + escape_string(value) + '"'
    raise EvalError(f"unsupported value: {value!r}")


def _arity_error(name, expected, got):
    return EvalError(f"{name}() takes {expected} argument(s), got {got}")


def _check_arity(name, args, expected):
    if len(args) != expected:
        raise _arity_error(name, expected, len(args))


def _check_number(name, value, ordinal=None):
    if not is_number(value):
        where = "" if ordinal is None else f" (argument {ordinal})"
        raise EvalError(f"{name}() expects a number{where}, got {_type_name(value)}")
    return value


def _check_string(name, value, ordinal=None):
    if not is_string(value):
        where = "" if ordinal is None else f" (argument {ordinal})"
        raise EvalError(f"{name}() expects a string{where}, got {_type_name(value)}")
    return value


def _type_name(value):
    if is_boolean(value):
        return "boolean"
    if is_number(value):
        return "number"
    if is_string(value):
        return "string"
    return type(value).__name__


def _builtin_abs(args):
    _check_arity("abs", args, 1)
    return float(abs(_check_number("abs", args[0])))


def _builtin_min(args):
    if not args:
        # Variadic arity wording: "at least 1" fits the rule 27 template.
        raise _arity_error("min", "at least 1", 0)
    for index, arg in enumerate(args, start=1):
        _check_number("min", arg, index)
    return float(min(args))


def _builtin_max(args):
    if not args:
        # Same variadic arity wording as min().
        raise _arity_error("max", "at least 1", 0)
    for index, arg in enumerate(args, start=1):
        _check_number("max", arg, index)
    return float(max(args))


def _builtin_round(args):
    if len(args) not in (1, 2):
        # round() accepts two arities, so the expected part reads "1 or 2".
        raise _arity_error("round", "1 or 2", len(args))
    x = _check_number("round", args[0], 1)
    if len(args) == 1:
        return float(round(x))
    digits = _check_number("round", args[1], 2)
    if not math.isfinite(digits) or not digits.is_integer():
        raise EvalError("round() expects a whole number of digits")
    return float(round(x, int(digits)))


def _builtin_len(args):
    _check_arity("len", args, 1)
    return float(len(_check_string("len", args[0])))


def _builtin_upper(args):
    _check_arity("upper", args, 1)
    return _check_string("upper", args[0]).upper()


def _builtin_lower(args):
    _check_arity("lower", args, 1)
    return _check_string("lower", args[0]).lower()


def _builtin_str(args):
    _check_arity("str", args, 1)
    value = args[0]
    if is_string(value):
        # A string converts to itself; the surrounding quotes shown by the
        # REPL are a display concern, not part of the value.
        return value
    if is_boolean(value):
        return "true" if value else "false"
    if is_number(value):
        return format_number(value)
    raise EvalError(f"str() expects a value, got {_type_name(value)}")


def _builtin_num(args):
    _check_arity("num", args, 1)
    text = _check_string("num", args[0])
    try:
        return float(text)
    except ValueError:
        raise EvalError(f"cannot convert to number: {text!r}") from None


#: Eagerly-evaluated built-ins: name -> callable taking the argument list.
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

#: Built-ins whose arguments must not all be evaluated up front.
LAZY_BUILTINS = frozenset({"if"})

#: Every callable name known to minilang.
BUILTIN_NAMES = frozenset(BUILTINS) | LAZY_BUILTINS


def check_if_arity(argument_count):
    """Arity check for the lazy ``if`` built-in."""
    if argument_count != 3:
        raise _arity_error("if", 3, argument_count)


def check_if_condition(value):
    if not is_boolean(value):
        raise EvalError(f"if() expects a boolean condition, got {_type_name(value)}")
    return value
