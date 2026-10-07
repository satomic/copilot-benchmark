"""Value types, SQL predicates, and numeric operations."""

from .errors import TypeMismatchError


def type_of(v: object) -> str:
    kinds = {int: "INT", float: "FLOAT", str: "TEXT", bool: "BOOL", type(None): "NULL"}
    try:
        return kinds[type(v)]
    except KeyError:
        raise TypeMismatchError(f"Unsupported value type: {type(v).__name__}") from None


def is_numeric(v: object) -> bool:
    return type(v) in (int, float)


def logical(v: object) -> bool | None:
    if v is None or type(v) is bool:
        return v
    raise TypeMismatchError(f"Expected BOOL or NULL, got {type_of(v)}")


def and_(a: bool | None, b: bool | None) -> bool | None:
    logical(a)
    logical(b)
    if a is False or b is False:
        return False
    return None if a is None or b is None else True


def or_(a: bool | None, b: bool | None) -> bool | None:
    logical(a)
    logical(b)
    if a is True or b is True:
        return True
    return None if a is None or b is None else False


def not_(a: bool | None) -> bool | None:
    logical(a)
    return None if a is None else not a


def comparable(a: object, b: object) -> bool:
    if a is None or b is None:
        return False
    if (is_numeric(a) and is_numeric(b)) or type_of(a) == type_of(b):
        return True
    raise TypeMismatchError(f"Cannot compare {type_of(a)} with {type_of(b)}")


def compare_eq(a: object, b: object) -> bool | None:
    return a == b if comparable(a, b) else None


def compare_lt(a: object, b: object) -> bool | None:
    return a < b if comparable(a, b) else None


def arith(op: str, a: object, b: object) -> object:
    if op not in ("+", "-", "*", "/", "%"):
        raise TypeMismatchError(f"Unknown arithmetic operator: {op}")
    if a is None or b is None:
        return None
    if not is_numeric(a) or not is_numeric(b):
        raise TypeMismatchError("Arithmetic requires numeric operands")
    if op == "%" and (type(a) is not int or type(b) is not int):
        raise TypeMismatchError("Modulo requires INT operands")
    if op in ("/", "%") and b == 0:
        return None
    if op == "+":
        return a + b
    if op == "-":
        return a - b
    if op == "*":
        return a * b
    if op == "/":
        return a / b
    return a % b


def negate(a: object) -> object:
    if a is None:
        return None
    if not is_numeric(a):
        raise TypeMismatchError("Negation requires a numeric operand")
    return -a


def key(v: object) -> tuple[str, object]:
    # Grouping and DISTINCT share reflexive NULL equality, but not BOOL/INT equality.
    kind = type_of(v)
    return ("NUMBER" if is_numeric(v) else kind, v)
