"""Value model: type names, three-valued logic, comparison and arithmetic."""

from .errors import TypeMismatchError


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
    raise TypeMismatchError(f"unsupported value {v!r}")


def is_numeric(v: object) -> bool:
    """True for INT and FLOAT values; bool is excluded."""
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def as_logical(v: object) -> bool | None:
    """Accept a logical value (bool or UNKNOWN); reject anything else."""
    if v is None or isinstance(v, bool):
        return v
    raise TypeMismatchError(f"expected a logical value, got {type_of(v)}")


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


def _kind(v: object) -> str:
    return "NUM" if is_numeric(v) else type_of(v)


def _check_comparable(a: object, b: object) -> None:
    if _kind(a) != _kind(b):
        raise TypeMismatchError(f"cannot compare {type_of(a)} with {type_of(b)}")


def compare_eq(a: object, b: object) -> bool | None:
    """SQL equality: UNKNOWN (None) if either side is NULL."""
    if a is None or b is None:
        return None
    _check_comparable(a, b)
    return a == b


def compare_lt(a: object, b: object) -> bool | None:
    """SQL less-than: UNKNOWN (None) if either side is NULL."""
    if a is None or b is None:
        return None
    _check_comparable(a, b)
    return a < b


def compare(op: str, a: object, b: object) -> bool | None:
    """Evaluate one of the six comparison operators with NULL propagation."""
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
    raise ValueError(f"unknown comparison {op}")


def arith(op: str, a: object, b: object) -> object:
    """Arithmetic with NULL propagation; division or modulo by zero gives NULL."""
    if a is None or b is None:
        return None
    if not (is_numeric(a) and is_numeric(b)):
        raise TypeMismatchError(f"operator {op} requires numeric operands")
    if op == "%":
        if type_of(a) != "INT" or type_of(b) != "INT":
            raise TypeMismatchError("operator % requires INT operands")
        return None if b == 0 else a % b
    if op == "/":
        return None if b == 0 else a / b
    if op == "+":
        return a + b
    if op == "-":
        return a - b
    if op == "*":
        return a * b
    raise ValueError(f"unknown operator {op}")


def negate(a: object) -> object:
    if a is None:
        return None
    if not is_numeric(a):
        raise TypeMismatchError(f"cannot negate {type_of(a)}")
    return -a


def group_key(v: object) -> tuple:
    """Hashable grouping/DISTINCT key in which NULL equals NULL.

    Booleans are kept apart from numbers so that True does not merge with 1.
    """
    if v is None:
        return ("NULL",)
    if isinstance(v, bool):
        return ("BOOL", v)
    if isinstance(v, (int, float)):
        return ("NUM", v)
    return ("TEXT", v)
