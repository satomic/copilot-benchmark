"""Value model, three-valued logic, comparison and arithmetic."""

from __future__ import annotations

from microdb.errors import TypeMismatchError


def type_of(v: object) -> str:
    """Return the microdb type name of a value."""
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
    raise TypeMismatchError(f"Unsupported value type: {type(v).__name__}")


def is_numeric(v: object) -> bool:
    """Return True for int and float, False for bool and None."""
    if isinstance(v, bool):
        return False
    return isinstance(v, (int, float))


def _ensure_boolean(v: object, name: str) -> None:
    if v is not None and not isinstance(v, bool):
        raise TypeMismatchError(
            f"Expected boolean or NULL for {name}, got {type_of(v)}"
        )


def and_(a: bool | None, b: bool | None) -> bool | None:
    """Three-valued AND logic."""
    _ensure_boolean(a, "AND left operand")
    _ensure_boolean(b, "AND right operand")
    if a is False or b is False:
        return False
    if a is True and b is True:
        return True
    return None


def or_(a: bool | None, b: bool | None) -> bool | None:
    """Three-valued OR logic."""
    _ensure_boolean(a, "OR left operand")
    _ensure_boolean(b, "OR right operand")
    if a is True or b is True:
        return True
    if a is False and b is False:
        return False
    return None


def not_(a: bool | None) -> bool | None:
    """Three-valued NOT logic."""
    _ensure_boolean(a, "NOT operand")
    if a is None:
        return None
    return not a


def _check_comparable(a: object, b: object) -> None:
    if is_numeric(a) and is_numeric(b):
        return
    if isinstance(a, str) and isinstance(b, str):
        return
    if isinstance(a, bool) and isinstance(b, bool):
        return
    raise TypeMismatchError(f"Cannot compare {type_of(a)} and {type_of(b)}")


def compare_eq(a: object, b: object) -> bool | None:
    """Compare equality with SQL three-valued logic."""
    if a is None or b is None:
        return None
    _check_comparable(a, b)
    return a == b


def compare_lt(a: object, b: object) -> bool | None:
    """Compare less-than with SQL three-valued logic."""
    if a is None or b is None:
        return None
    _check_comparable(a, b)
    return a < b


def arith(op: str, a: object, b: object) -> object:
    """Evaluate binary arithmetic with NULL propagation and zero division handling."""
    if a is None or b is None:
        return None
    if not is_numeric(a) or not is_numeric(b):
        raise TypeMismatchError(
            f"Arithmetic requires numeric operands, got {type_of(a)} and {type_of(b)}"
        )
    if op == "/":
        if b == 0:
            return None
        return float(a) / float(b)
    if op == "%":
        if not (isinstance(a, int) and isinstance(b, int)):
            raise TypeMismatchError("% requires two INT operands")
        if b == 0:
            return None
        return a % b
    if op == "+":
        res = a + b
    elif op == "-":
        res = a - b
    elif op == "*":
        res = a * b
    else:
        raise ValueError(f"Unknown arithmetic operator: {op}")
    return float(res) if isinstance(a, float) or isinstance(b, float) else res


def negate(a: object) -> object:
    """Unary arithmetic negation with NULL propagation."""
    if a is None:
        return None
    if not is_numeric(a):
        raise TypeMismatchError(f"Negate requires numeric operand, got {type_of(a)}")
    return -a
