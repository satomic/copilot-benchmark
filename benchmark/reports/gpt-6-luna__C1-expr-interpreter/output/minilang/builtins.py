from .errors import EvalError


def format_number(value: float) -> str:
    if value.is_integer():
        return str(int(value))
    return repr(value)


def format_value(value: object) -> str:
    if type(value) is bool:
        return "true" if value else "false"
    if type(value) is float:
        return format_number(value)
    if type(value) is str:
        escaped = value.replace("\\", "\\\\").replace('"', '\\"')
        escaped = escaped.replace("\n", "\\n").replace("\t", "\\t").replace("\r", "\\r")
        return f'"{escaped}"'
    raise EvalError(f"unsupported value: {value!r}")


def _arity(name: str, expected: str, count: int) -> None:
    if expected == "one or more":
        valid = count >= 1
    elif expected == "one or two":
        valid = count in (1, 2)
    else:
        valid = count == int(expected)
    if not valid:
        raise EvalError(f"{name}() takes {expected} argument(s), got {count}")


def check_arity(name: str, count: int) -> None:
    if name in {"abs", "len", "upper", "lower", "str", "num"}:
        _arity(name, "1", count)
    elif name in {"min", "max"}:
        _arity(name, "one or more", count)
    elif name == "round":
        _arity(name, "one or two", count)
    elif name == "if":
        _arity(name, "3", count)


def _number(name: str, value: object) -> float:
    if type(value) is not float:
        raise EvalError(f"{name}() expects number arguments")
    return value


def _string(name: str, value: object) -> str:
    if type(value) is not str:
        raise EvalError(f"{name}() expects a string")
    return value


def call_builtin(name: str, arguments: list[object]) -> object:
    count = len(arguments)
    check_arity(name, count)
    if name == "abs":
        return abs(_number(name, arguments[0]))
    if name in ("min", "max"):
        values = [_number(name, value) for value in arguments]
        return min(values) if name == "min" else max(values)
    if name == "round":
        value = _number(name, arguments[0])
        if count == 1:
            return float(round(value))
        digits = _number(name, arguments[1])
        if not digits.is_integer():
            raise EvalError("round() second argument must be a whole number")
        try:
            return float(round(value, int(digits)))
        except OverflowError as error:
            raise EvalError(str(error)) from error
    if name == "len":
        return float(len(_string(name, arguments[0])))
    if name == "upper":
        return _string(name, arguments[0]).upper()
    if name == "lower":
        return _string(name, arguments[0]).lower()
    if name == "str":
        return format_value(arguments[0])
    if name == "num":
        text = _string(name, arguments[0])
        try:
            return float(text)
        except ValueError as error:
            raise EvalError(f"num() could not parse number: {text!r}") from error
    if name == "if":
        raise AssertionError("if() must be evaluated lazily")
    raise EvalError(f"undefined function: {name}")


BUILTIN_NAMES = frozenset(
    {"abs", "min", "max", "round", "len", "upper", "lower", "str", "num", "if"}
)
