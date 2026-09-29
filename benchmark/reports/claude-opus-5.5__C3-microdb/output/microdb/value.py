"""Value model: types, three-valued logic, comparison and arithmetic."""

from __future__ import annotations

from .errors import TypeMismatchError

TYPE_NAMES = ("INT", "FLOAT", "TEXT", "BOOL")


def type_of(v: object) -> str:
    """Return the microdb type name of a Python value."""
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
    """True for int and float values, never for bool or None."""
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _check_logical(v: object) -> None:
    if v is not None and not isinstance(v, bool):
        raise TypeMismatchError(f"expected a BOOL value, got {type_of(v)}")


def and_(a: bool | None, b: bool | None) -> bool | None:
    """Three-valued AND."""
    _check_logical(a)
    _check_logical(b)
    if a is False or b is False:
        return False
    if a is None or b is None:
        return None
    return True


def or_(a: bool | None, b: bool | None) -> bool | None:
    """Three-valued OR."""
    _check_logical(a)
    _check_logical(b)
    if a is True or b is True:
        return True
    if a is None or b is None:
        return None
    return False


def not_(a: bool | None) -> bool | None:
    """Three-valued NOT."""
    _check_logical(a)
    if a is None:
        return None
    return not a


def require_logical(v: object) -> bool | None:
    """Return v if it is a logical value, else raise TypeMismatchError."""
    _check_logical(v)
    return v  # type: ignore[return-value]


def _check_comparable(a: object, b: object) -> None:
    if is_numeric(a) and is_numeric(b):
        return
    if isinstance(a, str) and isinstance(b, str):
        return
    if isinstance(a, bool) and isinstance(b, bool):
        return
    raise TypeMismatchError(f"cannot compare {type_of(a)} with {type_of(b)}")


def compare_eq(a: object, b: object) -> bool | None:
    """SQL equality: UNKNOWN when either side is NULL."""
    if a is None or b is None:
        return None
    _check_comparable(a, b)
    return a == b


def compare_lt(a: object, b: object) -> bool | None:
    """SQL less-than: UNKNOWN when either side is NULL."""
    if a is None or b is None:
        return None
    _check_comparable(a, b)
    return a < b  # type: ignore[operator]


def compare(op: str, a: object, b: object) -> bool | None:
    """Evaluate any comparison operator (= <> < <= > >=)."""
    if op == "=":
        return compare_eq(a, b)
    if op == "<>":
        return not_(compare_eq(a, b))
    if op == "<":
        return compare_lt(a, b)
    if op == ">":
        return compare_lt(b, a)
    if op == "<=":
        return or_(compare_lt(a, b), compare_eq(a, b))
    if op == ">=":
        return or_(compare_lt(b, a), compare_eq(a, b))
    raise ValueError(f"unknown comparison operator {op!r}")


def arith(op: str, a: object, b: object) -> object:
    """Evaluate a binary arithmetic operator (+ - * / %)."""
    if a is None or b is None:
        return None
    if not (is_numeric(a) and is_numeric(b)):
        raise TypeMismatchError(
            f"operator {op} requires numeric operands, got {type_of(a)} and {type_of(b)}"
        )
    if op == "+":
        return a + b  # type: ignore[operator]
    if op == "-":
        return a - b  # type: ignore[operator]
    if op == "*":
        return a * b  # type: ignore[operator]
    if op == "/":
        if b == 0:
            return None
        return float(a / b)  # type: ignore[operator]
    if op == "%":
        if not (type(a) is int and type(b) is int):
            raise TypeMismatchError("operator % requires INT operands")
        if b == 0:
            return None
        return a % b
    raise ValueError(f"unknown arithmetic operator {op!r}")


def negate(a: object) -> object:
    """Unary minus; preserves the numeric type, NULL propagates."""
    if a is None:
        return None
    if not is_numeric(a):
        raise TypeMismatchError(f"cannot negate {type_of(a)}")
    return -a  # type: ignore[operator]


def group_key(v: object) -> tuple:
    """Hashable key where NULL equals NULL and BOOL never equals a number."""
    if v is None:
        return ("NULL",)
    if isinstance(v, bool):
        return ("BOOL", v)
    if is_numeric(v):
        return ("NUM", v)
    return ("TEXT", v)


def row_key(values: list[object]) -> tuple:
    """Hashable key of a whole row for grouping and DISTINCT."""
    return tuple(group_key(v) for v in values)
