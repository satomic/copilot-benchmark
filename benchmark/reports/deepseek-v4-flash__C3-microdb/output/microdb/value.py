"""Value model, three-valued logic, comparison, arithmetic."""

from microdb.errors import TypeMismatchError


def type_of(v: object) -> str:
    """Return the type name of a value: INT, FLOAT, TEXT, BOOL, or NULL."""
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
    raise TypeMismatchError(f"unsupported type: {type(v).__name__}")


def is_numeric(v: object) -> bool:
    """True for int and float, False for bool and None."""
    return isinstance(v, (int, float)) and not isinstance(v, bool)


# ── Three-valued logic ──────────────────────────────────────────────────


def and_(a: bool | None, b: bool | None) -> bool | None:
    """Three-valued logical AND."""
    if a is False or b is False:
        return False
    if a is None or b is None:
        return None
    return True


def or_(a: bool | None, b: bool | None) -> bool | None:
    """Three-valued logical OR."""
    if a is True or b is True:
        return True
    if a is None or b is None:
        return None
    return False


def not_(a: bool | None) -> bool | None:
    """Three-valued logical NOT."""
    if a is None:
        return None
    return not a


# ── Comparison ──────────────────────────────────────────────────────────


def compare_eq(a: object, b: object) -> bool | None:
    """Compare a == b with NULL semantics and type checking.

    Returns UNKNOWN (None) if either operand is NULL.
    """
    if a is None or b is None:
        return None
    _check_comparable(a, b)
    return _py_eq(a, b)


def compare_lt(a: object, b: object) -> bool | None:
    """Compare a < b with NULL semantics and type checking.

    Returns UNKNOWN (None) if either operand is NULL.
    """
    if a is None or b is None:
        return None
    _check_comparable(a, b)
    return _py_lt(a, b)


def _check_comparable(a: object, b: object) -> None:
    """Raise TypeMismatchError if a and b cannot be compared."""
    ta = type_of(a)
    tb = type_of(b)
    if ta == tb:
        return
    # INT and FLOAT are comparable with each other
    if {ta, tb} <= {"INT", "FLOAT"}:
        return
    raise TypeMismatchError(
        f"cannot compare {ta} with {tb}"
    )


def _py_eq(a: object, b: object) -> bool:
    """Python-level equality, handling numeric type promotion."""
    ta = type_of(a)
    tb = type_of(b)
    if ta == "INT" and tb == "FLOAT":
        return a == b  # int == float works in Python
    if ta == "FLOAT" and tb == "INT":
        return a == b
    return a == b


def _py_lt(a: object, b: object) -> bool:
    """Python-level less-than, handling numeric type promotion."""
    ta = type_of(a)
    tb = type_of(b)
    if ta == "INT" and tb == "FLOAT":
        return a < b
    if ta == "FLOAT" and tb == "INT":
        return a < b
    return a < b


# ── Arithmetic ──────────────────────────────────────────────────────────


def arith(op: str, a: object, b: object) -> object:
    """Perform arithmetic operation. op in '+-*/%'.

    Returns NULL on NULL input or division by zero.
    """
    if a is None or b is None:
        return None

    ta = type_of(a)
    tb = type_of(b)

    if not is_numeric(a) or not is_numeric(b):
        raise TypeMismatchError(
            f"arithmetic {op} requires numeric operands, got {ta}, {tb}"
        )

    if op == "+":
        if ta == "FLOAT" or tb == "FLOAT":
            return float(a) + float(b)
        return a + b
    elif op == "-":
        if ta == "FLOAT" or tb == "FLOAT":
            return float(a) - float(b)
        return a - b
    elif op == "*":
        if ta == "FLOAT" or tb == "FLOAT":
            return float(a) * float(b)
        return a * b
    elif op == "/":
        b_val = float(b)
        if b_val == 0.0:
            return None
        return float(a) / b_val
    elif op == "%":
        if ta != "INT" or tb != "INT":
            raise TypeMismatchError(
                f"modulo requires INT operands, got {ta}, {tb}"
            )
        if b == 0:
            return None
        return a % b
    else:
        raise ValueError(f"unknown arithmetic operator: {op}")


def negate(a: object) -> object:
    """Negate a numeric value. NULL propagates."""
    if a is None:
        return None
    if not is_numeric(a):
        raise TypeMismatchError(
            f"negate requires numeric operand, got {type_of(a)}"
        )
    return -a