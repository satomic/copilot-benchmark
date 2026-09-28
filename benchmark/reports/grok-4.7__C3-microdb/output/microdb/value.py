"""Value model, three-valued logic, comparison and arithmetic."""

from __future__ import annotations

from microdb.errors import TypeMismatchError

_CMP = {"=", "<>", "<", "<=", ">", ">="}
_ARITH = {"+", "-", "*", "/", "%"}


def type_of(v: object) -> str:
    """Return INT, FLOAT, TEXT, BOOL, or NULL."""
    if v is None:
        return "NULL"
    if type(v) is bool:
        return "BOOL"
    if type(v) is int:
        return "INT"
    if type(v) is float:
        return "FLOAT"
    if type(v) is str:
        return "TEXT"
    raise TypeMismatchError(f"unsupported value {v!r}")


def is_numeric(v: object) -> bool:
    """True for int and float. False for bool and NULL."""
    return type(v) is int or type(v) is float


def and_(a: bool | None, b: bool | None) -> bool | None:
    """Three-valued AND. False wins over UNKNOWN."""
    if a is False or b is False:
        return False
    if a is True and b is True:
        return True
    return None


def or_(a: bool | None, b: bool | None) -> bool | None:
    """Three-valued OR. True wins over UNKNOWN."""
    if a is True or b is True:
        return True
    if a is False and b is False:
        return False
    return None


def not_(a: bool | None) -> bool | None:
    """Three-valued NOT. NOT UNKNOWN is UNKNOWN."""
    if a is None:
        return None
    return not a


def compare_eq(a: object, b: object) -> bool | None:
    """Equality. NULL compared with anything, including NULL, is UNKNOWN."""
    if a is None or b is None:
        return None
    if is_numeric(a) and is_numeric(b):
        return a == b  # type: ignore[operator]
    if type(a) is bool and type(b) is bool:
        return a == b
    if type(a) is str and type(b) is str:
        return a == b
    raise TypeMismatchError(f"cannot compare {type_of(a)} and {type_of(b)}")


def compare_lt(a: object, b: object) -> bool | None:
    """Less-than. NULL compared with anything is UNKNOWN."""
    if a is None or b is None:
        return None
    if is_numeric(a) and is_numeric(b):
        return a < b  # type: ignore[operator]
    if type(a) is bool and type(b) is bool:
        return a < b
    if type(a) is str and type(b) is str:
        return a < b
    raise TypeMismatchError(f"cannot compare {type_of(a)} and {type_of(b)}")


def compare(op: str, a: object, b: object) -> bool | None:
    """Compare using section 3.1 and three-valued logic."""
    if op == "=":
        return compare_eq(a, b)
    if op == "<>":
        return not_(compare_eq(a, b))
    if op == "<":
        return compare_lt(a, b)
    if op == "<=":
        return or_(compare_lt(a, b), compare_eq(a, b))
    if op == ">":
        return not_(or_(compare_lt(a, b), compare_eq(a, b)))
    if op == ">=":
        return not_(compare_lt(a, b))
    raise TypeMismatchError(f"unknown comparison {op}")


def negate(a: object) -> object:
    """Numeric negation. NULL stays NULL. Type is preserved."""
    if a is None:
        return None
    if type(a) is int:
        return -a
    if type(a) is float:
        return -a
    raise TypeMismatchError(f"cannot negate {type_of(a)}")


def arith(op: str, a: object, b: object) -> object:
    """Arithmetic. NULL propagates. Division by zero yields NULL."""
    if op not in _ARITH:
        raise TypeMismatchError(f"unknown operator {op}")
    if a is None or b is None:
        return None
    _require_numeric(a, op)
    _require_numeric(b, op)
    if op == "%":
        return _mod(a, b)
    if op == "/":
        return _div(a, b)
    return _add_sub_mul(op, a, b)


def _require_numeric(v: object, op: str) -> None:
    if not is_numeric(v):
        raise TypeMismatchError(f"operator {op} requires numeric operands, got {type_of(v)}")


def _is_zero(v: object) -> bool:
    return v == 0


def _mod(a: object, b: object) -> object:
    if type(a) is not int or type(b) is not int:
        raise TypeMismatchError("modulo requires two INT operands")
    if _is_zero(b):
        return None
    return a % b  # type: ignore[operator]


def _div(a: object, b: object) -> object:
    if _is_zero(b):
        return None
    return float(a) / float(b)  # type: ignore[arg-type]


def _add_sub_mul(op: str, a: object, b: object) -> object:
    if type(a) is int and type(b) is int:
        return _int_op(op, a, b)
    return _float_op(op, float(a), float(b))  # type: ignore[arg-type]


def _int_op(op: str, a: int, b: int) -> int:
    if op == "+":
        return a + b
    if op == "-":
        return a - b
    return a * b


def _float_op(op: str, a: float, b: float) -> float:
    if op == "+":
        return a + b
    if op == "-":
        return a - b
    return a * b
