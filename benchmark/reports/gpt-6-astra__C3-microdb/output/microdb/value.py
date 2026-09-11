"""Values, strict typing, and SQL three-valued operations."""

from .errors import TypeMismatchError


def type_of(v: object) -> str:
    kinds = {int: "INT", float: "FLOAT", str: "TEXT", bool: "BOOL",
             type(None): "NULL"}
    kind = kinds.get(type(v))
    if kind is None:
        raise TypeMismatchError(f"Unsupported value type: {type(v).__name__}")
    return kind


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


def _compatible(a: object, b: object) -> None:
    if is_numeric(a) and is_numeric(b):
        return
    if type_of(a) != type_of(b):
        raise TypeMismatchError(f"Cannot compare {type_of(a)} and {type_of(b)}")


def compare_eq(a: object, b: object) -> bool | None:
    if a is None or b is None:
        return None
    _compatible(a, b)
    return a == b


def compare_lt(a: object, b: object) -> bool | None:
    if a is None or b is None:
        return None
    _compatible(a, b)
    return a < b


def arith(op: str, a: object, b: object) -> object:
    if op not in ("+", "-", "*", "/", "%"):
        raise ValueError(f"Unknown arithmetic operator: {op}")
    if a is None or b is None:
        return None
    if not is_numeric(a) or not is_numeric(b):
        raise TypeMismatchError(f"{op} requires numeric operands")
    if op == "%" and (type(a) is not int or type(b) is not int):
        raise TypeMismatchError("% requires two INT operands")
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
        raise TypeMismatchError("Unary - requires a numeric operand")
    return -a


def equality_key(values: list[object] | tuple[object, ...]) -> tuple:
    # GROUP BY and DISTINCT use reflexive NULL equality, not SQL predicates.
    return tuple(("NUMBER" if is_numeric(v) else type_of(v), v) for v in values)
