"""Expression evaluation against a row plus a name resolution scope."""

from __future__ import annotations

import dataclasses

from .errors import (
    AmbiguousColumnError,
    ArityError,
    TypeMismatchError,
    UnknownColumnError,
    UnknownFunctionError,
    UnknownTableError,
)
from .parser import (
    Binary,
    Call,
    ColumnRef,
    Expr,
    IsNull,
    Literal,
    Logical,
    Not,
    Star,
    Unary,
)
from .value import (
    TEXT,
    and_,
    arith,
    compare_eq,
    compare_lt,
    is_numeric,
    negate,
    not_,
    or_,
    type_of,
)

__all__ = ["Scope", "evaluate", "as_condition", "SCALAR_ARITY"]

#: name -> (minimum, maximum or None for unbounded)
SCALAR_ARITY: dict[str, tuple[int, int | None]] = {
    "concat": (2, None),
    "upper": (1, 1),
    "lower": (1, 1),
    "length": (1, 1),
    "abs": (1, 1),
    "coalesce": (1, None),
}


@dataclasses.dataclass(frozen=True)
class Scope:
    """Maps column references to positions in a row.

    ``qualified`` holds ``(table, column) -> index`` and ``unqualified`` holds
    ``column -> [index, ...]`` so that an ambiguous name can be reported rather
    than silently resolved. ``aliases`` is consulted first and is how ORDER BY
    sees names that only exist in the projection.
    """

    qualified: dict[tuple[str, str], int]
    unqualified: dict[str, list[int]]
    tables: frozenset[str]
    aliases: dict[str, int] = dataclasses.field(default_factory=dict)

    def resolve(self, ref: ColumnRef) -> int:
        if ref.table is None:
            if ref.name in self.aliases:
                return self.aliases[ref.name]
            hits = self.unqualified.get(ref.name, [])
            if not hits:
                raise UnknownColumnError(f"unknown column {ref.name}")
            if len(hits) > 1:
                raise AmbiguousColumnError(f"column {ref.name} is ambiguous")
            return hits[0]
        if ref.table not in self.tables:
            raise UnknownTableError(f"unknown table {ref.table}")
        key = (ref.table, ref.name)
        if key not in self.qualified:
            raise UnknownColumnError(f"unknown column {ref.table}.{ref.name}")
        return self.qualified[key]


def _check_arity(name: str, count: int) -> None:
    low, high = SCALAR_ARITY[name]
    if count < low or (high is not None and count > high):
        expected = str(low) if high == low else (f"at least {low}" if high is None else f"{low} to {high}")
        raise ArityError(name, expected, count)


def _text_arg(name: str, value: object) -> object:
    if value is not None and type_of(value) != TEXT:
        raise TypeMismatchError(f"{name}() requires TEXT, got {type_of(value)}")
    return value


def _call_scalar(name: str, args: list[object]) -> object:
    lowered = name.lower()
    if lowered not in SCALAR_ARITY:
        raise UnknownFunctionError(f"unknown function {name}")
    _check_arity(lowered, len(args))
    if lowered == "coalesce":
        for value in args:
            if value is not None:
                return value
        return None
    if lowered == "concat":
        checked = [_text_arg("concat", a) for a in args]
        return None if any(a is None for a in checked) else "".join(checked)  # type: ignore[arg-type]
    value = args[0]
    if lowered in ("upper", "lower", "length"):
        _text_arg(lowered, value)
        if value is None:
            return None
        if lowered == "upper":
            return value.upper()  # type: ignore[union-attr]
        if lowered == "lower":
            return value.lower()  # type: ignore[union-attr]
        return len(value)  # type: ignore[arg-type]
    if value is None:
        return None
    if not is_numeric(value):
        raise TypeMismatchError(f"abs() requires a number, got {type_of(value)}")
    return abs(value)  # type: ignore[arg-type]


def _compare(op: str, left: object, right: object) -> bool | None:
    if op == "=":
        return compare_eq(left, right)
    if op == "<>":
        return not_(compare_eq(left, right))
    if op == "<":
        return compare_lt(left, right)
    if op == ">":
        return compare_lt(right, left)
    if op == "<=":
        return or_(compare_lt(left, right), compare_eq(left, right))
    return or_(compare_lt(right, left), compare_eq(left, right))


def evaluate(
    node: Expr,
    row: list[object],
    scope: Scope,
    aggregates: dict[str, object] | None = None,
) -> object:
    """Evaluate ``node``. ``aggregates`` maps aggregate source text to its value."""
    if isinstance(node, Literal):
        return node.value
    if isinstance(node, ColumnRef):
        return row[scope.resolve(node)]
    if isinstance(node, Star):
        raise TypeMismatchError("* is only valid inside count(*)")
    if isinstance(node, Unary):
        return negate(evaluate(node.operand, row, scope, aggregates))
    if isinstance(node, Not):
        return not_(_logical(node.operand, row, scope, aggregates))
    if isinstance(node, Logical):
        left = _logical(node.left, row, scope, aggregates)
        right = _logical(node.right, row, scope, aggregates)
        return and_(left, right) if node.op == "AND" else or_(left, right)
    if isinstance(node, IsNull):
        value = evaluate(node.operand, row, scope, aggregates)
        return (value is not None) if node.negated else (value is None)
    if isinstance(node, Binary):
        left = evaluate(node.left, row, scope, aggregates)
        right = evaluate(node.right, row, scope, aggregates)
        if node.op in ("=", "<>", "<", "<=", ">", ">="):
            return _compare(node.op, left, right)
        return arith(node.op, left, right)
    if isinstance(node, Call):
        if node.is_aggregate:
            if aggregates is None or node.source not in aggregates:
                raise TypeMismatchError(f"aggregate {node.source} is not available here")
            return aggregates[node.source]
        return _call_scalar(node.name, [evaluate(a, row, scope, aggregates) for a in node.args])
    raise TypeMismatchError(f"cannot evaluate {node!r}")


def _logical(
    node: Expr, row: list[object], scope: Scope, aggregates: dict[str, object] | None
) -> bool | None:
    """Evaluate a subexpression that must produce a logical value."""
    value = evaluate(node, row, scope, aggregates)
    if value is None or isinstance(value, bool):
        return value
    raise TypeMismatchError(f"expected a BOOL condition, got {type_of(value)}")


def as_condition(
    node: Expr, row: list[object], scope: Scope, aggregates: dict[str, object] | None = None
) -> bool | None:
    """Public wrapper used by the executor for WHERE, HAVING and ON."""
    return _logical(node, row, scope, aggregates)

