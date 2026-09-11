"""The value model: five value kinds and three-valued logic.

NULL is represented by Python's ``None`` and is not a distinct "type" -- it is
the absence of a value permitted in any column.  ``bool`` is always treated as
a distinct kind from ``int``, even though ``isinstance(True, int)`` is true in
Python, so every numeric check here explicitly excludes ``bool``.
"""

from __future__ import annotations

from microdb.errors import TypeMismatchError

Value = object  # int | float | str | bool | None


def type_of(v: Value) -> str:
    """Return the microdb type name of ``v``: INT, FLOAT, TEXT, BOOL or NULL."""
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
    raise TypeMismatchError(f"unsupported value: {v!r}")


def is_numeric(v: Value) -> bool:
    """Return True if v is an INT or FLOAT (not BOOL, not NULL)."""
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def and_(a: bool | None, b: bool | None) -> bool | None:
    """Three-valued AND."""
    if a is False or b is False:
        return False
    if a is None or b is None:
        return None
    return True


def or_(a: bool | None, b: bool | None) -> bool | None:
    """Three-valued OR."""
    if a is True or b is True:
        return True
    if a is None or b is None:
        return None
    return False


def not_(a: bool | None) -> bool | None:
    """Three-valued NOT."""
    if a is None:
        return None
    return not a


def compare_eq(a: Value, b: Value) -> bool | None:
    """Three-valued equality comparison."""
    if a is None or b is None:
        return None
    if isinstance(a, bool) or isinstance(b, bool):
        if isinstance(a, bool) and isinstance(b, bool):
            return a == b
        raise TypeMismatchError(f"cannot compare {type_of(a)} with {type_of(b)}")
    if is_numeric(a) and is_numeric(b):
        return a == b
    if isinstance(a, str) and isinstance(b, str):
        return a == b
    raise TypeMismatchError(f"cannot compare {type_of(a)} with {type_of(b)}")


def compare_lt(a: Value, b: Value) -> bool | None:
    """Three-valued less-than comparison."""
    if a is None or b is None:
        return None
    if isinstance(a, bool) or isinstance(b, bool):
        if isinstance(a, bool) and isinstance(b, bool):
            return bool(a) < bool(b)
        raise TypeMismatchError(f"cannot compare {type_of(a)} with {type_of(b)}")
    if is_numeric(a) and is_numeric(b):
        return a < b
    if isinstance(a, str) and isinstance(b, str):
        return a < b
    raise TypeMismatchError(f"cannot compare {type_of(a)} with {type_of(b)}")


def _check_numeric(a: Value, b: Value) -> None:
    if not is_numeric(a) or not is_numeric(b):
        raise TypeMismatchError(f"arithmetic requires numeric operands, got {type_of(a)} and {type_of(b)}")


def arith(op: str, a: Value, b: Value) -> Value:
    """Apply arithmetic operator op in '+-*/%' to a and b, per section 3.2."""
    if a is None or b is None:
        return None
    if op == "%":
        if not isinstance(a, int) or not isinstance(b, int) or isinstance(a, bool) or isinstance(b, bool):
            raise TypeMismatchError("% requires two INT operands")
        if b == 0:
            return None
        return a % b
    _check_numeric(a, b)
    if op == "/":
        if b == 0:
            return None
        return float(a) / float(b)
    if op in ("+", "-", "*"):
        result = {"+": a + b, "-": a - b, "*": a * b}[op]
        if isinstance(a, float) or isinstance(b, float):
            return float(result)
        return int(result)
    raise TypeMismatchError(f"unknown operator: {op}")


def negate(a: Value) -> Value:
    """Unary negation; preserves type; NULL propagates."""
    if a is None:
        return None
    if not is_numeric(a):
        raise TypeMismatchError(f"cannot negate {type_of(a)}")
    return -a
