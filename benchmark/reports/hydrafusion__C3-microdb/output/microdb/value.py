from .errors import TypeMismatchError


def type_of(v: object) -> str:
    if v is None:
        return "NULL"
    if isinstance(v, bool):
        return "BOOL"
    if isinstance(v, int):
        return "INT"
    if isinstance(v, float):
        return "FLOAT"
    if isinstance(v, str):
        return "TEXT"
    raise TypeMismatchError(f"unsupported value type: {type(v).__name__}")


def is_numeric(v: object) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def and_(a: bool | None, b: bool | None) -> bool | None:
    if a is False or b is False:
        return False
    if a is None or b is None:
        return None
    return True


def or_(a: bool | None, b: bool | None) -> bool | None:
    if a is True or b is True:
        return True
    if a is None or b is None:
        return None
    return False


def not_(a: bool | None) -> bool | None:
    return None if a is None else not a


def _compatible(a: object, b: object) -> bool:
    ta, tb = type_of(a), type_of(b)
    return (is_numeric(a) and is_numeric(b)) or ta == tb


def compare_eq(a: object, b: object) -> bool | None:
    if a is None or b is None:
        return None
    if not _compatible(a, b):
        raise TypeMismatchError(f"cannot compare {type_of(a)} with {type_of(b)}")
    return bool(a == b)


def compare_lt(a: object, b: object) -> bool | None:
    if a is None or b is None:
        return None
    if not _compatible(a, b):
        raise TypeMismatchError(f"cannot compare {type_of(a)} with {type_of(b)}")
    return bool(a < b)  # type: ignore[operator]


def arith(op: str, a: object, b: object) -> object:
    if a is None or b is None:
        return None
    if not is_numeric(a) or not is_numeric(b):
        raise TypeMismatchError(f"{op} requires numeric operands")
    if op == "%":
        if type_of(a) != "INT" or type_of(b) != "INT":
            raise TypeMismatchError("% requires INT operands")
        return None if b == 0 else a % b  # type: ignore[operator]
    if op == "/":
        return None if b == 0 else float(a) / float(b)
    if op == "+":
        return a + b  # type: ignore[operator]
    if op == "-":
        return a - b  # type: ignore[operator]
    if op == "*":
        return a * b  # type: ignore[operator]
    raise ValueError(f"unknown arithmetic operator {op}")


def negate(a: object) -> object:
    if a is None:
        return None
    if not is_numeric(a):
        raise TypeMismatchError("unary - requires a numeric operand")
    return -a  # type: ignore[operator]
