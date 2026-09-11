"""The value model: types, three-valued logic, comparison and arithmetic.

Every NULL rule in the engine funnels through this module, so that the three
places that need it (WHERE, aggregates, ORDER BY) cannot drift apart.
"""

from __future__ import annotations

from .errors import TypeMismatchError

__all__ = [
    "INT",
    "FLOAT",
    "TEXT",
    "BOOL",
    "NULL",
    "TYPE_NAMES",
    "type_of",
    "is_numeric",
    "and_",
    "or_",
    "not_",
    "compare_eq",
    "compare_lt",
    "arith",
    "negate",
    "sort_key_lt",
]

INT = "INT"
FLOAT = "FLOAT"
TEXT = "TEXT"
BOOL = "BOOL"
NULL = "NULL"
TYPE_NAMES = (INT, FLOAT, TEXT, BOOL)


def type_of(v: object) -> str:
    """Return the type name of a value. bool is checked before int on purpose."""
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
    raise TypeMismatchError(f"unsupported Python value {v!r}")


def is_numeric(v: object) -> bool:
    """True only for INT and FLOAT. bool is not numeric here."""
    return type_of(v) in (INT, FLOAT)


# -- three-valued logic -------------------------------------------------------


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


# -- comparison ---------------------------------------------------------------


def _comparable(a: object, b: object) -> None:
    """Raise unless the two non-NULL values may be compared."""
    ta, tb = type_of(a), type_of(b)
    if is_numeric(a) and is_numeric(b):
        return
    if ta == tb and ta in (TEXT, BOOL):
        return
    raise TypeMismatchError(f"cannot compare {ta} with {tb}")


def compare_eq(a: object, b: object) -> bool | None:
    """Equality with SQL semantics: NULL on either side gives UNKNOWN."""
    if a is None or b is None:
        return None
    _comparable(a, b)
    return a == b


def compare_lt(a: object, b: object) -> bool | None:
    """Strict less-than with SQL semantics."""
    if a is None or b is None:
        return None
    _comparable(a, b)
    return a < b


def sort_key_lt(a: object, b: object) -> bool:
    """Total order used by ORDER BY, where NULL is greater than everything.

    Unlike :func:`compare_lt` this never returns UNKNOWN, because a sort needs a
    total order. Type mismatches still raise.
    """
    if a is None and b is None:
        return False
    if a is None:
        return False
    if b is None:
        return True
    _comparable(a, b)
    return a < b


# -- arithmetic ---------------------------------------------------------------


def _require_numeric(op: str, *values: object) -> None:
    for v in values:
        if not is_numeric(v):
            raise TypeMismatchError(f"operator {op} requires numbers, got {type_of(v)}")


def arith(op: str, a: object, b: object) -> object:
    """Binary arithmetic. NULL propagates; division by zero yields NULL."""
    if a is None or b is None:
        return None
    if op == "%":
        if type_of(a) != INT or type_of(b) != INT:
            raise TypeMismatchError(
                f"operator % requires two INT, got {type_of(a)} and {type_of(b)}"
            )
        return None if b == 0 else a % b
    _require_numeric(op, a, b)
    if op == "+":
        return a + b
    if op == "-":
        return a - b
    if op == "*":
        return a * b
    if op == "/":
        # Always FLOAT, and a zero divisor is a NULL rather than an error.
        return None if float(b) == 0.0 else float(a) / float(b)
    raise TypeMismatchError(f"unknown operator {op}")


def negate(a: object) -> object:
    if a is None:
        return None
    _require_numeric("unary -", a)
    return -a
