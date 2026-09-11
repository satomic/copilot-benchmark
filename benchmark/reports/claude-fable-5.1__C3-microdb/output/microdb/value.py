"""Value model: type classification, three-valued logic, comparison and arithmetic."""

from __future__ import annotations

from .errors import TypeMismatchError

TYPE_NAMES = ("INT", "FLOAT", "TEXT", "BOOL")


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
    raise TypeMismatchError(f"unsupported Python value {v!r}")


def is_numeric(v: object) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def is_logical(v: object) -> bool:
    return v is None or isinstance(v, bool)


# --- three-valued logic -------------------------------------------------------


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
    if a is None:
        return None
    return not a


# --- comparison ---------------------------------------------------------------


def _check_comparable(a: object, b: object) -> None:
    ta, tb = type_of(a), type_of(b)
    if is_numeric(a) and is_numeric(b):
        return
    if ta == tb and ta in ("TEXT", "BOOL"):
        return
    raise TypeMismatchError(f"cannot compare {ta} with {tb}")


def compare_eq(a: object, b: object) -> bool | None:
    if a is None or b is None:
        return None
    _check_comparable(a, b)
    return a == b


def compare_lt(a: object, b: object) -> bool | None:
    if a is None or b is None:
        return None
    _check_comparable(a, b)
    return a < b


def compare(a: object, b: object) -> int:
    """Total ordering of two non-NULL values: -1, 0 or 1."""
    if compare_lt(a, b):
        return -1
    if compare_lt(b, a):
        return 1
    return 0


# --- arithmetic ---------------------------------------------------------------


def _require_numeric(op: str, v: object) -> None:
    if not is_numeric(v):
        raise TypeMismatchError(f"operator {op!r} requires numeric operands, got {type_of(v)}")


def arith(op: str, a: object, b: object) -> object:
    if op not in "+-*/%" or len(op) != 1:
        raise ValueError(f"unknown arithmetic operator {op!r}")
    if a is None or b is None:
        return None
    _require_numeric(op, a)
    _require_numeric(op, b)
    if op == "+":
        return a + b
    if op == "-":
        return a - b
    if op == "*":
        return a * b
    if op == "/":
        if b == 0:
            return None
        return a / b
    if not (isinstance(a, int) and isinstance(b, int)):
        raise TypeMismatchError("operator '%' requires INT operands")
    if b == 0:
        return None
    return a % b


def negate(a: object) -> object:
    if a is None:
        return None
    _require_numeric("-", a)
    return -a


def concat(*args: object) -> object:
    """Concatenate TEXT values; NULL if any argument is NULL."""
    for v in args:
        if v is not None and not isinstance(v, str):
            raise TypeMismatchError(f"concat requires TEXT arguments, got {type_of(v)}")
    if any(v is None for v in args):
        return None
    return "".join(args)  # type: ignore[arg-type]


def hash_key(v: object) -> tuple:
    """A hashable key under which 1, 1.0 collide but True and 1 do not.

    Used for GROUP BY and DISTINCT, where NULL is equal to NULL.
    """
    if v is None:
        return ("NULL",)
    if is_numeric(v):
        return ("NUM", v)
    return (type_of(v), v)
