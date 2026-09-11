"""Value model: type inspection, three-valued logic, comparison and arithmetic.

There are exactly five value kinds.  NULL is represented by ``None`` and is not a
type of its own: it may appear in a column of any type.  ``bool`` is deliberately
treated as a distinct type even though Python considers it a subclass of ``int``.
"""

from __future__ import annotations

from .errors import TypeMismatchError

INT: str = "INT"
FLOAT: str = "FLOAT"
TEXT: str = "TEXT"
BOOL: str = "BOOL"
NULL: str = "NULL"

TYPE_NAMES: frozenset[str] = frozenset({INT, FLOAT, TEXT, BOOL})


def type_of(v: object) -> str:
    """Return the type name of ``v``, or ``"NULL"`` when ``v`` is ``None``."""
    if v is None:
        return NULL
    if isinstance(v, bool):
        return BOOL
    if isinstance(v, int):
        return INT
    if isinstance(v, float):
        return FLOAT
    if isinstance(v, str):
        return TEXT
    raise TypeMismatchError(f"unsupported value of Python type {type(v).__name__!r}")


def is_numeric(v: object) -> bool:
    """Return True for ``int`` and ``float`` values, excluding ``bool`` and ``None``."""
    if isinstance(v, bool) or v is None:
        return False
    return isinstance(v, (int, float))


def is_bool(v: object) -> bool:
    """Return True when ``v`` is a genuine boolean value."""
    return isinstance(v, bool)


def is_text(v: object) -> bool:
    """Return True when ``v`` is a text value."""
    return isinstance(v, str)


# --------------------------------------------------------------------------
# Three-valued logic.  ``None`` stands for UNKNOWN.
# --------------------------------------------------------------------------


def and_(a: bool | None, b: bool | None) -> bool | None:
    """Three-valued AND: FALSE dominates, so ``FALSE AND UNKNOWN`` is FALSE."""
    if a is False or b is False:
        return False
    if a is None or b is None:
        return None
    return True


def or_(a: bool | None, b: bool | None) -> bool | None:
    """Three-valued OR: TRUE dominates, so ``TRUE OR UNKNOWN`` is TRUE."""
    if a is True or b is True:
        return True
    if a is None or b is None:
        return None
    return False


def not_(a: bool | None) -> bool | None:
    """Three-valued NOT: ``NOT UNKNOWN`` stays UNKNOWN."""
    if a is None:
        return None
    return not a


# --------------------------------------------------------------------------
# Comparison
# --------------------------------------------------------------------------


def _check_comparable(a: object, b: object) -> None:
    """Raise TypeMismatchError unless ``a`` and ``b`` are in the same comparison class."""
    if is_numeric(a) and is_numeric(b):
        return
    if is_bool(a) and is_bool(b):
        return
    if is_text(a) and is_text(b):
        return
    raise TypeMismatchError(
        f"cannot compare {type_of(a)} with {type_of(b)}"
    )


def compare_eq(a: object, b: object) -> bool | None:
    """SQL ``=``: UNKNOWN when either side is NULL, even for ``NULL = NULL``."""
    if a is None or b is None:
        return None
    _check_comparable(a, b)
    return a == b


def compare_lt(a: object, b: object) -> bool | None:
    """SQL ``<``: UNKNOWN when either side is NULL."""
    if a is None or b is None:
        return None
    _check_comparable(a, b)
    return a < b


def compare_op(op: str, a: object, b: object) -> bool | None:
    """Evaluate one of ``= <> < <= > >=`` with three-valued semantics."""
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
    raise TypeMismatchError(f"unknown comparison operator {op!r}")


def order_lt(a: object, b: object) -> bool:
    """Strict ordering between two non-NULL values, used by sorting and MIN/MAX."""
    result = compare_lt(a, b)
    return bool(result)


# --------------------------------------------------------------------------
# Arithmetic
# --------------------------------------------------------------------------


def _require_numeric(op: str, *values: object) -> None:
    for v in values:
        if not is_numeric(v):
            raise TypeMismatchError(
                f"operator {op!r} requires numeric operands, got {type_of(v)}"
            )


def arith(op: str, a: object, b: object) -> object:
    """Binary arithmetic with NULL propagation and NULL on division by zero."""
    if a is None or b is None:
        return None
    _require_numeric(op, a, b)
    if op == "+":
        return a + b
    if op == "-":
        return a - b
    if op == "*":
        return a * b
    if op == "/":
        if b == 0:
            return None
        return float(a) / float(b)
    if op == "%":
        if type_of(a) != INT or type_of(b) != INT:
            raise TypeMismatchError("operator '%' requires two INT operands")
        if b == 0:
            return None
        return a % b
    raise TypeMismatchError(f"unknown arithmetic operator {op!r}")


def negate(a: object) -> object:
    """Unary minus: NULL propagates and the numeric type is preserved."""
    if a is None:
        return None
    _require_numeric("-", a)
    return -a
