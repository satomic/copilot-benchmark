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
    return True if a is True and b is True else None


def or_(a: bool | None, b: bool | None) -> bool | None:
    if a is True or b is True:
        return True
    return False if a is False and b is False else None


def not_(a: bool | None) -> bool | None:
    return None if a is None else not a


def _compatible(a: object, b: object) -> str:
    ta, tb = type_of(a), type_of(b)
    if "NULL" in (ta, tb):
        return "NULL"
    if {ta, tb} <= {"INT", "FLOAT"}:
        return "NUM"
    if ta == tb:
        return ta
    raise TypeMismatchError(f"cannot compare {ta} and {tb}")


def compare_eq(a: object, b: object) -> bool | None:
    kind = _compatible(a, b)
    return None if kind == "NULL" else a == b


def compare_lt(a: object, b: object) -> bool | None:
    kind = _compatible(a, b)
    return None if kind == "NULL" else a < b


def arith(op: str, a: object, b: object) -> object:
    if a is None or b is None:
        return None
    if not is_numeric(a) or not is_numeric(b):
        raise TypeMismatchError("arithmetic requires numeric operands")
    if op == "/" and b == 0 or op == "%" and b == 0:
        return None
    if op == "%":
        if not isinstance(a, int) or not isinstance(b, int):
            raise TypeMismatchError("modulo requires integers")
        return a % b
    if op == "/":
        return float(a) / float(b)
    return {"+": lambda: a + b, "-": lambda: a - b,
            "*": lambda: a * b}[op]()


def negate(a: object) -> object:
    if a is None:
        return None
    if not is_numeric(a):
        raise TypeMismatchError("negation requires numeric operand")
    return -a
