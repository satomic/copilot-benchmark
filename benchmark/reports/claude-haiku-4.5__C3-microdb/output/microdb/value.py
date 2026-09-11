from .errors import TypeMismatchError


def type_of(v: object) -> str:
    """Return the type name of a value."""
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
    return "NULL"


def is_numeric(v: object) -> bool:
    """Check if a value is numeric (INT or FLOAT, not BOOL)."""
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def and_(a: bool | None, b: bool | None) -> bool | None:
    """Three-valued AND."""
    if a is False or b is False:
        return False
    if a is True and b is True:
        return True
    if a is True:
        return b
    if b is True:
        return a
    return None


def or_(a: bool | None, b: bool | None) -> bool | None:
    """Three-valued OR."""
    if a is True or b is True:
        return True
    if a is False and b is False:
        return False
    if a is False:
        return b
    if b is False:
        return a
    return None


def not_(a: bool | None) -> bool | None:
    """Three-valued NOT."""
    if a is True:
        return False
    if a is False:
        return True
    return None


def compare_eq(a: object, b: object) -> bool | None:
    """Three-valued equality comparison."""
    if a is None or b is None:
        return None
    ta, tb = type_of(a), type_of(b)
    if ta == "BOOL" or tb == "BOOL":
        if ta != tb:
            raise TypeMismatchError(f"Cannot compare {ta} and {tb}")
        return a == b
    if ta in ("INT", "FLOAT") and tb in ("INT", "FLOAT"):
        return a == b
    if ta == "TEXT" and tb == "TEXT":
        return a == b
    if ta != tb:
        raise TypeMismatchError(f"Cannot compare {ta} and {tb}")
    return a == b


def compare_lt(a: object, b: object) -> bool | None:
    """Three-valued less-than comparison."""
    if a is None or b is None:
        return None
    ta, tb = type_of(a), type_of(b)
    if ta == "BOOL" or tb == "BOOL":
        if ta != tb:
            raise TypeMismatchError(f"Cannot compare {ta} and {tb}")
        return a < b
    if ta in ("INT", "FLOAT") and tb in ("INT", "FLOAT"):
        return a < b
    if ta == "TEXT" and tb == "TEXT":
        return a < b
    raise TypeMismatchError(f"Cannot compare {ta} and {tb}")


def arith(op: str, a: object, b: object) -> object:
    """Arithmetic operation."""
    if a is None or b is None:
        return None
    if not is_numeric(a) or not is_numeric(b):
        raise TypeMismatchError(
            f"Cannot perform {op} on {type_of(a)} and {type_of(b)}"
        )
    if op == "+":
        return a + b if not isinstance(a, float) and not isinstance(b, float) else float(a) + float(b)
    if op == "-":
        return a - b if not isinstance(a, float) and not isinstance(b, float) else float(a) - float(b)
    if op == "*":
        return a * b if not isinstance(a, float) and not isinstance(b, float) else float(a) * float(b)
    if op == "/":
        if a == 0 or b == 0:
            return None
        return float(a) / float(b)
    if op == "%":
        if not isinstance(a, int) or not isinstance(b, int):
            raise TypeMismatchError(f"Modulo requires INT operands")
        if b == 0:
            return None
        return a % b
    raise ValueError(f"Unknown operator: {op}")


def negate(a: object) -> object:
    """Unary negation."""
    if a is None:
        return None
    if not is_numeric(a):
        raise TypeMismatchError(f"Cannot negate {type_of(a)}")
    return -a
