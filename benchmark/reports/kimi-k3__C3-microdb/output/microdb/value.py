"""Value model: five kinds (INT, FLOAT, TEXT, BOOL, NULL), three-valued logic,
comparison and arithmetic with SQL NULL semantics.

Note: ``bool`` is a subclass of ``int`` in Python, so every numeric check in this
module excludes ``bool`` explicitly.
"""

from __future__ import annotations

from .errors import TypeMismatchError

INT = "INT"
FLOAT = "FLOAT"
TEXT = "TEXT"
BOOL = "BOOL"
NULL = "NULL"


def type_of(v: object) -> str:
    """Return the kind name of a value: INT, FLOAT, TEXT, BOOL or NULL."""
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
    raise TypeMismatchError(f"unsupported value: {v!r}")


def is_numeric(v: object) -> bool:
    """True for INT and FLOAT values; False for BOOL, TEXT and NULL."""
    return isinstance(v, (int, float)) and not isinstance(v, bool)


# ---------------------------------------------------------------------------
# Three-valued logic.  A logical value is True, False or None (UNKNOWN).
# ---------------------------------------------------------------------------

def and_(a: bool | None, b: bool | None) -> bool | None:
    """Logical AND under three-valued logic."""
    if a is False or b is False:
        return False
    if a is None or b is None:
        return None
    return True


def or_(a: bool | None, b: bool | None) -> bool | None:
    """Logical OR under three-valued logic."""
    if a is True or b is True:
        return True
    if a is None or b is None:
        return None
    return False


def not_(a: bool | None) -> bool | None:
    """Logical NOT under three-valued logic; NOT UNKNOWN is UNKNOWN."""
    if a is None:
        return None
    return not a


# ---------------------------------------------------------------------------
# Comparison
# ---------------------------------------------------------------------------

def _cmp_operands(a: object, b: object) -> tuple[object, object]:
    """Validate a pair of non-NULL operands for comparison."""
    ta, tb = type_of(a), type_of(b)
    if is_numeric(a) and is_numeric(b):
        return a, b
    if ta == TEXT and tb == TEXT:
        return a, b
    if ta == BOOL and tb == BOOL:
        return a, b
    raise TypeMismatchError(f"cannot compare {ta} with {tb}")


def compare_eq(a: object, b: object) -> bool | None:
    """Equality comparison; UNKNOWN (None) if either operand is NULL."""
    if a is None or b is None:
        return None
    x, y = _cmp_operands(a, b)
    return bool(x == y)


def compare_lt(a: object, b: object) -> bool | None:
    """Less-than comparison; UNKNOWN (None) if either operand is NULL."""
    if a is None or b is None:
        return None
    x, y = _cmp_operands(a, b)
    return bool(x < y)


# ---------------------------------------------------------------------------
# Arithmetic
# ---------------------------------------------------------------------------

def arith(op: str, a: object, b: object) -> object:
    """Apply an arithmetic operator ('+', '-', '*', '/', '%') with NULL
    propagation.  Division or modulo by zero yields NULL, not an error."""
    if a is None or b is None:
        return None
    if not is_numeric(a) or not is_numeric(b):
        raise TypeMismatchError(
            f"operator {op} requires numeric operands, "
            f"got {type_of(a)} and {type_of(b)}"
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
        return a / b  # type: ignore[operator]  # always FLOAT
    if op == "%":
        if type_of(a) != INT or type_of(b) != INT:
            raise TypeMismatchError("operator % requires INT operands")
        if b == 0:
            return None
        return a % b  # type: ignore[operator]
    raise TypeMismatchError(f"unknown arithmetic operator {op!r}")


def negate(a: object) -> object:
    """Unary minus; requires a numeric operand and preserves its type."""
    if a is None:
        return None
    if not is_numeric(a):
        raise TypeMismatchError(f"cannot negate {type_of(a)}")
    return -a  # type: ignore[operator]
