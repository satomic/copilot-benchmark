from __future__ import annotations

from collections.abc import Callable, Sequence

from .errors import ArityError, TypeMismatchError, UnknownFunctionError
from .parser import AGGREGATES, Expr
from .value import and_, arith, compare_eq, compare_lt, is_numeric, negate, not_, type_of, or_


Resolver = Callable[[tuple[str | None, str]], object]
Evaluator = Callable[[Expr, object], object]
TypeResolver = Callable[[tuple[str | None, str]], str]


def is_aggregate(expr: Expr) -> bool:
    return expr.kind == "CALL" and str(expr.value).lower() in AGGREGATES


def contains_aggregate(expr: Expr) -> bool:
    return is_aggregate(expr) or any(contains_aggregate(child) for child in expr.children)


def infer_type(expr: Expr, resolver: TypeResolver) -> str:
    if expr.kind == "LITERAL":
        return type_of(expr.value)
    if expr.kind == "COLUMN":
        return resolver(expr.value)  # type: ignore[arg-type]
    if expr.kind == "STAR":
        return "STAR"
    if expr.kind == "NEGATE":
        kind = infer_type(expr.children[0], resolver)
        _require_numeric(kind, "unary -")
        return kind
    if expr.kind in {"NOT", "IS_NULL", "IS_NOT_NULL"}:
        kind = infer_type(expr.children[0], resolver)
        if expr.kind == "NOT" and kind not in {"BOOL", "NULL", "ANY"}:
            raise TypeMismatchError(f"logical operation requires BOOL, got {kind}")
        return "BOOL"
    if expr.kind == "BINARY":
        return _infer_binary(expr, resolver)
    if expr.kind == "CALL":
        return _infer_call(expr, resolver)
    raise ValueError(f"unknown expression kind: {expr.kind}")


def _infer_binary(expr: Expr, resolver: TypeResolver) -> str:
    left = infer_type(expr.children[0], resolver)
    right = infer_type(expr.children[1], resolver)
    operator = str(expr.value).upper()
    if operator in {"AND", "OR"}:
        for kind in (left, right):
            if kind not in {"BOOL", "NULL", "ANY"}:
                raise TypeMismatchError(f"logical operation requires BOOL, got {kind}")
        return "BOOL"
    if operator in {"=", "<>", "<", "<=", ">", ">="}:
        _require_comparable(left, right)
        return "BOOL"
    if left == "NULL" or right == "NULL":
        return "NULL"
    if left == "ANY" or right == "ANY":
        return "ANY"
    _require_numeric(left, operator)
    _require_numeric(right, operator)
    if operator == "%" and (left != "INT" or right != "INT"):
        raise TypeMismatchError("% requires INT operands")
    if operator == "/":
        return "FLOAT"
    if left == "FLOAT" or right == "FLOAT":
        return "FLOAT"
    return "INT"


def _infer_call(expr: Expr, resolver: TypeResolver) -> str:
    name = str(expr.value).lower()
    kinds = [infer_type(child, resolver) for child in expr.children]
    if name == "count":
        return "INT"
    if name == "avg":
        if kinds[0] != "NULL":
            _require_numeric(kinds[0], name)
        return "FLOAT"
    if name == "sum":
        kind = kinds[0]
        if kind != "NULL":
            _require_numeric(kind, name)
        return "FLOAT" if kind in {"FLOAT", "ANY"} else kind
    if name in {"min", "max"}:
        return kinds[0]
    if name == "coalesce":
        known = [kind for kind in kinds if kind != "NULL"]
        return known[0] if known and all(kind == known[0] for kind in known) else "ANY"
    if name == "concat":
        _require_text(kinds, name)
        return "TEXT"
    if name in {"upper", "lower"}:
        _require_text(kinds, name)
        return "TEXT"
    if name == "length":
        _require_text(kinds, name)
        return "INT"
    if name == "abs":
        _require_numeric(kinds[0], name)
        return kinds[0]
    return "ANY"


def _require_text(kinds: list[str], function: str) -> None:
    if any(kind not in {"TEXT", "NULL", "ANY"} for kind in kinds):
        raise TypeMismatchError(f"{function} requires TEXT arguments")


def _require_numeric(kind: str, operation: str) -> None:
    if kind not in {"INT", "FLOAT", "NULL", "ANY"}:
        raise TypeMismatchError(f"{operation} requires numeric operands")


def _require_comparable(left: str, right: str) -> None:
    if "NULL" in {left, right} or "ANY" in {left, right}:
        return
    if left in {"INT", "FLOAT"} and right in {"INT", "FLOAT"}:
        return
    if left != right or left not in {"TEXT", "BOOL"}:
        raise TypeMismatchError(f"cannot compare {left} with {right}")


def evaluate(expr: Expr, row: object, resolver: Resolver,
             group: Sequence[object] | None = None,
             row_resolver: Callable[[tuple[str | None, str], object], object] | None = None) -> object:
    kind = expr.kind
    if kind == "LITERAL":
        return expr.value
    if kind == "COLUMN":
        reference = expr.value
        return row_resolver(reference, row) if row_resolver else resolver(reference)  # type: ignore[arg-type]
    if kind == "STAR":
        return expr.value
    if kind == "NEGATE":
        return negate(evaluate(expr.children[0], row, resolver, group, row_resolver))
    if kind == "NOT":
        return not_(_logical(evaluate(expr.children[0], row, resolver, group, row_resolver)))
    if kind == "IS_NULL":
        return evaluate(expr.children[0], row, resolver, group, row_resolver) is None
    if kind == "IS_NOT_NULL":
        return evaluate(expr.children[0], row, resolver, group, row_resolver) is not None
    if kind == "BINARY":
        return _binary(expr, row, resolver, group, row_resolver)
    if kind == "CALL":
        return _call(expr, row, resolver, group, row_resolver)
    raise ValueError(f"unknown expression kind: {kind}")


def _binary(expr: Expr, row: object, resolver: Resolver,
            group: Sequence[object] | None,
            row_resolver: Callable[[tuple[str | None, str], object], object] | None) -> object:
    left = evaluate(expr.children[0], row, resolver, group, row_resolver)
    right = evaluate(expr.children[1], row, resolver, group, row_resolver)
    op = str(expr.value).upper()
    if op == "AND":
        return and_(_logical(left), _logical(right))
    if op == "OR":
        return or_(_logical(left), _logical(right))
    if op in {"+", "-", "*", "/", "%"}:
        return arith(op, left, right)
    if op == "=":
        return compare_eq(left, right)
    if op == "<>":
        equal = compare_eq(left, right)
        return None if equal is None else not equal
    if op in {"<", ">", "<=", ">="}:
        if op == "<":
            return compare_lt(left, right)
        if op == ">":
            return compare_lt(right, left)
        first = compare_lt(left, right)
        if op == "<=":
            return True if compare_eq(left, right) is True else first
        reverse = compare_lt(right, left)
        return True if compare_eq(left, right) is True else reverse
    raise ValueError(f"unknown operator: {op}")


def _call(expr: Expr, row: object, resolver: Resolver,
          group: Sequence[object] | None,
          row_resolver: Callable[[tuple[str | None, str], object], object] | None) -> object:
    name = str(expr.value).lower()
    if name in AGGREGATES:
        from .aggregate import evaluate_aggregate
        rows = group if group is not None else [row]
        return evaluate_aggregate(
            expr, rows,
            lambda child, current: evaluate(child, current, resolver, row_resolver=row_resolver),
        )
    values = [evaluate(child, row, resolver, group, row_resolver) for child in expr.children]
    return _scalar(name, values)


def _scalar(name: str, values: list[object]) -> object:
    arities = {"concat": (2, None), "upper": (1, 1), "lower": (1, 1),
               "length": (1, 1), "abs": (1, 1), "coalesce": (1, None)}
    if name not in arities:
        raise UnknownFunctionError(f"unknown function: {name}")
    minimum, maximum = arities[name]
    if len(values) < minimum or (maximum is not None and len(values) > maximum):
        upper = "unbounded" if maximum is None else str(maximum)
        raise ArityError(f"{name} expects {minimum}..{upper} arguments, got {len(values)}")
    if name == "coalesce":
        return next((value for value in values if value is not None), None)
    if name == "concat":
        if not all(value is None or isinstance(value, str) for value in values):
            raise TypeMismatchError("concat requires TEXT arguments")
        if any(value is None for value in values):
            return None
        return "".join(values)  # type: ignore[arg-type]
    value = values[0]
    if value is None:
        return None
    if name in {"upper", "lower", "length"}:
        if not isinstance(value, str):
            raise TypeMismatchError(f"{name} requires a TEXT argument")
        if name == "upper":
            return value.upper()
        if name == "lower":
            return value.lower()
        return len(value)
    if not is_numeric(value):
        raise TypeMismatchError("abs requires a numeric argument")
    return abs(value)


def _logical(value: object) -> bool | None:
    if value is None or isinstance(value, bool):
        return value
    raise TypeMismatchError(f"logical operation requires BOOL, got {type_of(value)}")
