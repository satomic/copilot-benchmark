"""Value model, three-valued logic, comparison and arithmetic."""

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
    raise TypeMismatchError(f"unsupported value {v!r}")


def is_numeric(v: object) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _check_logical(v: object) -> None:
    if v is not None and not isinstance(v, bool):
        raise TypeMismatchError(f"expected BOOL or NULL, got {type_of(v)}")


def and_(a: bool | None, b: bool | None) -> bool | None:
    _check_logical(a)
    _check_logical(b)
    if a is False or b is False:
        return False
    if a is None or b is None:
        return None
    return True


def or_(a: bool | None, b: bool | None) -> bool | None:
    _check_logical(a)
    _check_logical(b)
    if a is True or b is True:
        return True
    if a is None or b is None:
        return None
    return False


def not_(a: bool | None) -> bool | None:
    _check_logical(a)
    return None if a is None else (not a)


def _check_comparable(a: object, b: object) -> None:
    if is_numeric(a) and is_numeric(b):
        return
    if isinstance(a, str) and isinstance(b, str):
        return
    if isinstance(a, bool) and isinstance(b, bool):
        return
    raise TypeMismatchError(f"cannot compare {type_of(a)} with {type_of(b)}")


def compare_eq(a: object, b: object) -> bool | None:
    if a is None or b is None:
        return None
    _check_comparable(a, b)
    return a == b


def compare_lt(a: object, b: object) -> bool | None:
    if a is None or b is None:
        return None
    _check_comparable(a, b)
    return a < b  # type: ignore[operator]


def arith(op: str, a: object, b: object) -> object:
    if op not in ("+", "-", "*", "/", "%"):
        raise ValueError(f"unknown arithmetic operator {op!r}")
    if a is None or b is None:
        return None
    if not (is_numeric(a) and is_numeric(b)):
        raise TypeMismatchError(
            f"operator {op} needs numeric operands, got {type_of(a)} and {type_of(b)}"
        )
    if op == "%" and not (isinstance(a, int) and isinstance(b, int)):
        raise TypeMismatchError("operator % requires INT operands")
    if op in ("/", "%") and b == 0:
        return None
    if op == "+":
        return a + b  # type: ignore[operator]
    if op == "-":
        return a - b  # type: ignore[operator]
    if op == "*":
        return a * b  # type: ignore[operator]
    if op == "/":
        return a / b  # type: ignore[operator]
    return a % b  # type: ignore[operator]


def negate(a: object) -> object:
    if a is None:
        return None
    if not is_numeric(a):
        raise TypeMismatchError(f"cannot negate {type_of(a)}")
    return -a  # type: ignore[operator]
