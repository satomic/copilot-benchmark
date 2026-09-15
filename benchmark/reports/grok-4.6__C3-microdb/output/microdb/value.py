"""Value model, three-valued logic, comparison, and arithmetic."""

from __future__ import annotations

from microdb.errors import TypeMismatchError


def type_of(v: object) -> str:
    if v is None:
        return "NULL"
    if v is True or v is False:
        return "BOOL"
    if isinstance(v, int) and not isinstance(v, bool):
        return "INT"
    if isinstance(v, float):
        return "FLOAT"
    if isinstance(v, str):
        return "TEXT"
    raise TypeMismatchError(f"unsupported value {v!r}")


def is_numeric(v: object) -> bool:
    return type_of(v) in ("INT", "FLOAT")


def and_(a: bool | None, b: bool | None) -> bool | None:
    _check_logical(a)
    _check_logical(b)
    if a is False or b is False:
        return False
    if a is None or b is None:
        return None
    return True


def or_(a: bool | None, b: bool | None) -> bool | None:
    _check_logical(a)
    _check_logical(b)
    if a is True or b is True:
        return True
    if a is None or b is None:
        return None
    return False


def not_(a: bool | None) -> bool | None:
    _check_logical(a)
    if a is None:
        return None
    return not a


def compare_eq(a: object, b: object) -> bool | None:
    if a is None or b is None:
        return None
    ta, tb = type_of(a), type_of(b)
    if _numeric_pair(ta, tb):
        return a == b
    if ta == tb == "TEXT":
        return a == b
    if ta == tb == "BOOL":
        return a is b
    raise TypeMismatchError(f"cannot compare {ta} and {tb}")


def compare_lt(a: object, b: object) -> bool | None:
    if a is None or b is None:
        return None
    ta, tb = type_of(a), type_of(b)
    if _numeric_pair(ta, tb):
        return bool(a < b)  # type: ignore[operator]
    if ta == tb == "TEXT":
        return bool(a < b)  # type: ignore[operator]
    if ta == tb == "BOOL":
        return (not a) and b
    raise TypeMismatchError(f"cannot compare {ta} and {tb}")


def compare_ne(a: object, b: object) -> bool | None:
    return not_(compare_eq(a, b))


def compare_le(a: object, b: object) -> bool | None:
    return or_(compare_lt(a, b), compare_eq(a, b))


def compare_gt(a: object, b: object) -> bool | None:
    return compare_lt(b, a)


def compare_ge(a: object, b: object) -> bool | None:
    return or_(compare_lt(b, a), compare_eq(a, b))


def arith(op: str, a: object, b: object) -> object:
    if a is None or b is None:
        return None
    if not is_numeric(a) or not is_numeric(b):
        raise TypeMismatchError(f"arithmetic on {type_of(a)} and {type_of(b)}")
    if op == "+":
        return _num_result(a, b, a + b)  # type: ignore[operator]
    if op == "-":
        return _num_result(a, b, a - b)  # type: ignore[operator]
    if op == "*":
        return _num_result(a, b, a * b)  # type: ignore[operator]
    if op == "/":
        return _div(a, b)
    if op == "%":
        return _mod(a, b)
    raise TypeMismatchError(f"unknown arithmetic operator {op}")


def negate(a: object) -> object:
    if a is None:
        return None
    if not is_numeric(a):
        raise TypeMismatchError(f"cannot negate {type_of(a)}")
    return -a  # type: ignore[operator]


def as_logical(v: object) -> bool | None:
    if v is True or v is False or v is None:
        return v
    raise TypeMismatchError(f"expected BOOL, got {type_of(v)}")


def group_canon(v: object) -> tuple[object, ...]:
    if v is None:
        return ("NULL",)
    kind = type_of(v)
    if kind == "INT":
        return ("NUM", float(v))  # type: ignore[arg-type]
    if kind == "FLOAT":
        return ("NUM", v)
    if kind == "BOOL":
        return ("BOOL", v)
    return ("TEXT", v)


def distinct_canon(v: object) -> tuple[object, ...]:
    if v is None:
        return ("NULL",)
    return (type_of(v), v)


def _check_logical(v: bool | None) -> None:
    if v is not True and v is not False and v is not None:
        raise TypeMismatchError("logical operand must be BOOL or NULL")


def _numeric_pair(ta: str, tb: str) -> bool:
    return ta in ("INT", "FLOAT") and tb in ("INT", "FLOAT")


def _num_result(a: object, b: object, result: object) -> object:
    if type_of(a) == "INT" and type_of(b) == "INT":
        return int(result)  # type: ignore[arg-type]
    return float(result)  # type: ignore[arg-type]


def _div(a: object, b: object) -> object:
    bf = float(b)  # type: ignore[arg-type]
    if bf == 0.0:
        return None
    return float(a) / bf  # type: ignore[arg-type]


def _mod(a: object, b: object) -> object:
    if type_of(a) != "INT" or type_of(b) != "INT":
        raise TypeMismatchError("% requires INT operands")
    if b == 0:
        return None
    return a % b  # type: ignore[operator]
