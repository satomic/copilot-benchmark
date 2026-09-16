from .errors import EvalError

BUILTIN_NAMES = {"abs", "min", "max", "round", "len", "upper", "lower", "str", "num", "if"}


def _arity(name, expected, got):
    if got != expected:
        raise EvalError(f"{name}() takes {expected} argument(s), got {got}")


def _number(name, value):
    if type(value) is not float:
        raise EvalError(f"{name}() requires number arguments")


def call_builtin(name, args):
    if name == "abs":
        _arity(name, 1, len(args)); _number(name, args[0]); return abs(args[0])
    if name in ("min", "max"):
        if not args: raise EvalError(f"{name}() takes 1 or more argument(s), got 0")
        for x in args: _number(name, x)
        return (min if name == "min" else max)(args)
    if name == "round":
        if len(args) not in (1, 2): raise EvalError(f"round() takes 1 or 2 argument(s), got {len(args)}")
        _number(name, args[0])
        if len(args) == 2:
            _number(name, args[1])
            if not args[1].is_integer(): raise EvalError("round() precision must be a whole number")
            return float(round(args[0], int(args[1])))
        return float(round(args[0]))
    if name == "len":
        _arity(name, 1, len(args))
        if type(args[0]) is not str: raise EvalError("len() requires a string")
        return float(len(args[0]))
    if name in ("upper", "lower"):
        _arity(name, 1, len(args))
        if type(args[0]) is not str: raise EvalError(f"{name}() requires a string")
        return args[0].upper() if name == "upper" else args[0].lower()
    if name == "str":
        _arity(name, 1, len(args))
        value = args[0]
        if type(value) is bool: return "true" if value else "false"
        if type(value) is float: return format_number(value)
        return value
    if name == "num":
        _arity(name, 1, len(args))
        if type(args[0]) is not str: raise EvalError("num() requires a string")
        try: return float(args[0])
        except ValueError: raise EvalError("num() argument is not a number")
    raise EvalError(f"undefined function: {name}")


def format_number(value):
    if value.is_integer():
        return str(int(value))
    return repr(value)
