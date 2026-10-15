from __future__ import annotations

from microdb.errors import TypeMismatchError

VALID_TYPES: frozenset[str] = frozenset({"INT", "FLOAT", "TEXT", "BOOL"})


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
    raise TypeMismatchError(f"Unsupported value: {v!r}")


def is_numeric(v: object) -> bool:
    return not isinstance(v, bool) and isinstance(v, (int, float))


def _ensure_logical(v: object) -> bool | None:
    if v is not None and not isinstance(v, bool):
        raise TypeMismatchError(f"Expected BOOL or NULL, got {type_of(v)}")
    return v


def and_(a: bool | None, b: bool | None) -> bool | None:
    la = _ensure_logical(a)
    lb = _ensure_logical(b)
    if la is False or lb is False:
        return False
    if la is True and lb is True:
        return True
    return None


def or_(a: bool | None, b: bool | None) -> bool | None:
    la = _ensure_logical(a)
    lb = _ensure_logical(b)
    if la is True or lb is True:
        return True
    if la is False and lb is False:
        return False
    return None


def not_(a: bool | None) -> bool | None:
    la = _ensure_logical(a)
    if la is None:
        return None
    return not la


def compare_eq(a: object, b: object) -> bool | None:
    if a is None or b is None:
        return None
    if is_numeric(a) and is_numeric(b):
        return bool(a == b)
    if isinstance(a, str) and isinstance(b, str):
        return a == b
    if isinstance(a, bool) and isinstance(b, bool):
        return a == b
    raise TypeMismatchError(f"Cannot compare {type_of(a)} and {type_of(b)}")


def compare_lt(a: object, b: object) -> bool | None:
    if a is None or b is None:
        return None
    if is_numeric(a) and is_numeric(b):
        return bool(a < b)  # type: ignore[operator]
    if isinstance(a, str) and isinstance(b, str):
        return a < b
    if isinstance(a, bool) and isinstance(b, bool):
        return (not a) and b
    raise TypeMismatchError(f"Cannot order {type_of(a)} and {type_of(b)}")


def compare(op: str, a: object, b: object) -> bool | None:
    if op == "=":
        return compare_eq(a, b)
    if op == "<>":
        return not_(compare_eq(a, b))
    if op == "<":
        return compare_lt(a, b)
    if op == ">":
        return compare_lt(b, a)
    if op == "<=":
        lt = compare_lt(a, b)
        eq = compare_eq(a, b)
        return None if (lt is None or eq is None) else (lt or eq)
    if op == ">=":
        gt = compare_lt(b, a)
        eq = compare_eq(a, b)
        return None if (gt is None or eq is None) else (gt or eq)
    raise ValueError(f"Unknown comparison operator: {op}")


def arith(op: str, a: object, b: object) -> object:
    if op not in {"+", "-", "*", "/", "%"}:
        raise ValueError(f"Unknown arithmetic operator: {op}")
    if (a is not None and not is_numeric(a)) or (b is not None and not is_numeric(b)):
        raise TypeMismatchError(f"Arithmetic {op!r} requires numeric operands")
    if op == "%":
        if (a is not None and type_of(a) != "INT") or (b is not None and type_of(b) != "INT"):
            raise TypeMismatchError("Modulo '%' requires INT operands")
    if a is None or b is None:
        return None
    assert isinstance(a, (int, float)) and isinstance(b, (int, float))
    if op == "+":
        return a + b
    if op == "-":
        return a - b
    if op == "*":
        return a * b
    if op == "/":
        return None if b == 0 else float(a) / float(b)
    return None if b == 0 else int(a) % int(b)


def negate(a: object) -> object:
    if a is None:
        return None
    if not is_numeric(a):
        raise TypeMismatchError(f"Unary minus requires numeric operand, got {type_of(a)}")
    assert isinstance(a, (int, float))
    return -a
