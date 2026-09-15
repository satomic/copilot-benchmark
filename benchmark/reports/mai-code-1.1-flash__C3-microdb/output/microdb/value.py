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
    raise TypeMismatchError(f"unsupported value: {v!r}")


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
    if a is None:
        return None
    return not a


def compare_eq(a: object, b: object) -> bool | None:
    if a is None or b is None:
        return None
    ta, tb = type_of(a), type_of(b)
    if (ta in {"INT", "FLOAT"} and tb in {"INT", "FLOAT"}) or (ta == "TEXT" and tb == "TEXT") or (ta == "BOOL" and tb == "BOOL"):
        if ta == "INT" and tb == "FLOAT":
            return float(a) == b
        if ta == "FLOAT" and tb == "INT":
            return a == float(b)
        return a == b
    raise TypeMismatchError(f"cannot compare {ta} and {tb}")


def compare_lt(a: object, b: object) -> bool | None:
    if a is None or b is None:
        return None
    ta, tb = type_of(a), type_of(b)
    if ta in {"INT", "FLOAT"} and tb in {"INT", "FLOAT"}:
        return float(a) < float(b)
    if ta == "TEXT" and tb == "TEXT":
        return a < b
    if ta == "BOOL" and tb == "BOOL":
        return a < b
    raise TypeMismatchError(f"cannot compare {ta} and {tb}")


def arith(op: str, a: object, b: object) -> object:
    if a is None or b is None:
        return None
    if not is_numeric(a) or not is_numeric(b):
        raise TypeMismatchError("arith expects numeric operands")
    if op == "%":
        if not isinstance(a, int) or not isinstance(b, int):
            raise TypeMismatchError("% requires INT operands")
        if b == 0:
            return None
        return a % b
    if op == "/":
        if b == 0:
            return None
        return float(a) / float(b)
    if op == "+":
        return a + b if isinstance(a, int) and isinstance(b, int) else float(a) + float(b)
    if op == "-":
        return a - b if isinstance(a, int) and isinstance(b, int) else float(a) - float(b)
    if op == "*":
        return a * b if isinstance(a, int) and isinstance(b, int) else float(a) * float(b)
    raise TypeMismatchError(f"unsupported op {op}")


def negate(a: object) -> object:
    if a is None:
        return None
    if isinstance(a, bool):
        raise TypeMismatchError("negate requires numeric operand")
    if isinstance(a, int):
        return -a
    if isinstance(a, float):
        return -a
    raise TypeMismatchError("negate requires numeric operand")
