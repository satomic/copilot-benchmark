from __future__ import annotations

from .aggregate import AGGREGATE_NAMES
from .errors import AggregateError, AmbiguousColumnError, ArityError, TypeMismatchError, UnknownColumnError, UnknownFunctionError, UnknownTableError
from .parser import BinaryOp, ColumnRef, FunctionCall, Literal, NullCheck, Star, UnaryOp
from .value import and_, arith, compare_eq, compare_lt, negate, not_, or_, type_of


def evaluate(expr: object, row: dict[str, object]) -> object:
    if isinstance(expr, Literal):
        return expr.value
    if isinstance(expr, ColumnRef):
        return _resolve_ref(row, expr)
    if isinstance(expr, UnaryOp):
        return _eval_unary(expr.op, expr.operand, row)
    if isinstance(expr, BinaryOp):
        return _eval_binary(expr.op, expr.left, expr.right, row)
    if isinstance(expr, FunctionCall):
        return _eval_call(expr, row)
    if isinstance(expr, NullCheck):
        return _eval_null_check(expr, row)
    if isinstance(expr, Star):
        return None
    raise TypeMismatchError("unsupported expression")


def _resolve_ref(row: dict[str, object], expr: ColumnRef) -> object:
    name = expr.name
    if expr.table is not None:
        key = f"{expr.table}.{name}"
        if key in row:
            return row[key]
        raise UnknownTableError(expr.table)
    ambig = row.get("__ambig__", set())
    if name in ambig:
        raise AmbiguousColumnError(name)
    if name in row:
        return row[name]
    src = row.get("__source__")
    if isinstance(src, dict):
        if name in src.get("__ambig__", set()):
            raise AmbiguousColumnError(name)
        if name in src:
            return src[name]
    raise UnknownColumnError(name)


def _eval_unary(op: str, operand: object, row: dict[str, object]) -> object:
    value = evaluate(operand, row)
    if op == "-":
        return negate(value)
    if op == "NOT":
        if not isinstance(value, bool) and value is not None:
            raise TypeMismatchError("NOT requires logical operand")
        return not_(value if value is None or isinstance(value, bool) else None)
    raise TypeMismatchError("unsupported unary op")


def _eval_binary(op: str, left: object, right: object, row: dict[str, object]) -> object:
    lv = evaluate(left, row)
    rv = evaluate(right, row)
    if op == "AND":
        if lv is not None and not isinstance(lv, bool):
            raise TypeMismatchError("AND requires bool")
        if rv is not None and not isinstance(rv, bool):
            raise TypeMismatchError("AND requires bool")
        return and_(lv, rv)
    if op == "OR":
        if lv is not None and not isinstance(lv, bool):
            raise TypeMismatchError("OR requires bool")
        if rv is not None and not isinstance(rv, bool):
            raise TypeMismatchError("OR requires bool")
        return or_(lv, rv)
    if op in {"=", "<>", "<", "<=", ">", ">="}:
        return _compare(op, lv, rv)
    if op in {"+", "-", "*", "/", "%"}:
        return arith(op, lv, rv)
    raise TypeMismatchError("unsupported binary op")


def _compare(op: str, left: object, right: object) -> object:
    if op == "=":
        return compare_eq(left, right)
    if op == "<>":
        eq = compare_eq(left, right)
        if eq is None:
            return None
        return not eq
    if op == "<":
        return compare_lt(left, right)
    if op == "<=":
        lt = compare_lt(left, right)
        eq = compare_eq(left, right)
        if lt is None or eq is None:
            return None
        return lt or eq
    if op == ">":
        lt = compare_lt(right, left)
        return lt
    if op == ">=":
        lt = compare_lt(right, left)
        eq = compare_eq(left, right)
        if lt is None or eq is None:
            return None
        return lt or eq
    raise TypeMismatchError("unsupported comparator")


def _eval_call(expr: FunctionCall, row: dict[str, object]) -> object:
    name = expr.name.lower()
    if name in AGGREGATE_NAMES:
        raise AggregateError(f"aggregate {name} not allowed here")
    if name == "concat":
        return _call_concat(expr.args, row)
    if name in {"upper", "lower"}:
        return _call_text(expr.args, row, name)
    if name == "length":
        return _call_length(expr.args, row)
    if name == "abs":
        return _call_abs(expr.args, row)
    if name == "coalesce":
        return _call_coalesce(expr.args, row)
    raise UnknownFunctionError(name)


def _eval_null_check(expr: NullCheck, row: dict[str, object]) -> bool | None:
    value = evaluate(expr.expr, row)
    if expr.op == "IS NULL":
        return value is None
    return value is not None


def _call_concat(args: list[object], row: dict[str, object]) -> object:
    values = [evaluate(a, row) for a in args]
    if len(values) < 2:
        raise ArityError("concat requires at least 2 args")
    for value in values:
        if value is None:
            return None
        if not isinstance(value, str):
            raise TypeMismatchError("concat requires TEXT")
    return "".join(values)


def _call_text(args: list[object], row: dict[str, object], name: str) -> object:
    if len(args) != 1:
        raise ArityError(f"{name} requires 1 arg")
    value = evaluate(args[0], row)
    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeMismatchError(f"{name} requires TEXT")
    return value.upper() if name == "upper" else value.lower()


def _call_length(args: list[object], row: dict[str, object]) -> object:
    if len(args) != 1:
        raise ArityError("length requires 1 arg")
    value = evaluate(args[0], row)
    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeMismatchError("length requires TEXT")
    return len(value)


def _call_abs(args: list[object], row: dict[str, object]) -> object:
    if len(args) != 1:
        raise ArityError("abs requires 1 arg")
    value = evaluate(args[0], row)
    if value is None:
        return None
    if value is None or isinstance(value, bool):
        raise TypeMismatchError("abs requires numeric")
    if isinstance(value, int):
        return abs(value)
    if isinstance(value, float):
        return abs(value)
    raise TypeMismatchError("abs requires numeric")


def _call_coalesce(args: list[object], row: dict[str, object]) -> object:
    if not args:
        raise ArityError("coalesce requires at least 1 arg")
    for arg in args:
        value = evaluate(arg, row)
        if value is not None:
            return value
    return None


def contains_aggregate(expr: object) -> bool:
    if isinstance(expr, FunctionCall):
        if expr.name.lower() in AGGREGATE_NAMES:
            return True
        return any(contains_aggregate(arg) for arg in expr.args)
    if isinstance(expr, UnaryOp):
        return contains_aggregate(expr.operand)
    if isinstance(expr, BinaryOp):
        return contains_aggregate(expr.left) or contains_aggregate(expr.right)
    if isinstance(expr, NullCheck):
        return contains_aggregate(expr.expr)
    return False


def expr_label(expr: object) -> str:
    if isinstance(expr, Literal):
        if expr.value is None:
            return "NULL"
        if isinstance(expr.value, bool):
            return "TRUE" if expr.value else "FALSE"
        return str(expr.value)
    if isinstance(expr, ColumnRef):
        return f"{expr.table}.{expr.name}" if expr.table else expr.name
    if isinstance(expr, UnaryOp):
        return f"{expr.op} {expr_label(expr.operand)}"
    if isinstance(expr, BinaryOp):
        return f"{expr_label(expr.left)} {expr.op} {expr_label(expr.right)}"
    if isinstance(expr, FunctionCall):
        parts = [expr.name]
        parts.append("(")
        args = []
        for arg in expr.args:
            if isinstance(arg, Star):
                args.append("*")
            else:
                args.append(expr_label(arg))
        parts.append(", ".join(args))
        parts.append(")")
        return "".join(parts)
    if isinstance(expr, NullCheck):
        return f"{expr_label(expr.expr)} {expr.op}"
    return "expr"
