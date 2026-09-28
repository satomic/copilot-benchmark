from __future__ import annotations

from .errors import TypeMismatchError


def type_of(v: object) -> str:
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
    raise TypeMismatchError(f"unsupported value type: {type(v).__name__}")


def is_numeric(v: object) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


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


def _compatible(a: object, b: object) -> bool:
    if is_numeric(a) and is_numeric(b):
        return True
    return type_of(a) == type_of(b) and type_of(a) in {"TEXT", "BOOL"}


def compare_eq(a: object, b: object) -> bool | None:
    if a is None or b is None:
        return None
    if not _compatible(a, b):
        raise TypeMismatchError(f"cannot compare {type_of(a)} with {type_of(b)}")
    return a == b


def compare_lt(a: object, b: object) -> bool | None:
    if a is None or b is None:
        return None
    if not _compatible(a, b):
        raise TypeMismatchError(f"cannot compare {type_of(a)} with {type_of(b)}")
    return a < b


def arith(op: str, a: object, b: object) -> object:
    if a is None or b is None:
        return None
    if op not in "+-*/%":
        raise ValueError(f"unsupported arithmetic operator: {op}")
    if not is_numeric(a) or not is_numeric(b):
        raise TypeMismatchError(f"{op} requires numeric operands")
    if op == "%" and (type_of(a) != "INT" or type_of(b) != "INT"):
        raise TypeMismatchError("% requires INT operands")
    if op in {"/", "%"} and b == 0:
        return None
    if op == "/":
        return float(a) / float(b)
    if op == "%":
        return int(a) % int(b)
    return {"+": lambda: a + b, "-": lambda: a - b, "*": lambda: a * b}[op]()


def negate(a: object) -> object:
    if a is None:
        return None
    if not is_numeric(a):
        raise TypeMismatchError("unary - requires a numeric operand")
    return -a
