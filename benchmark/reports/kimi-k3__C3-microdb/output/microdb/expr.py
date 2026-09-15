"""Expression evaluation.

A :class:`Row` is the evaluation context: cell values plus a scope describing
which (table, column) each position belongs to.  ``agg_values`` holds
precomputed aggregate results keyed by node identity (``id`` of the FuncCall
node); ``aliases`` maps SELECT alias names to this row's output values and is
only populated while evaluating ORDER BY (where an alias wins over an input
column of the same name).
"""

from __future__ import annotations

import dataclasses

from .aggregate import is_aggregate_name
from .errors import (
    AggregateError,
    AmbiguousColumnError,
    ArityError,
    TypeMismatchError,
    UnknownColumnError,
    UnknownFunctionError,
    UnknownTableError,
)
from .parser import BinaryOp, ColumnRef, FuncCall, IsNull, Literal, Node, NotOp, UnaryOp
from .value import (
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


@dataclasses.dataclass(frozen=True)
class Scope:
    """Column provenance for a row: (table name, column name) per position."""

    entries: tuple[tuple[str | None, str], ...]


@dataclasses.dataclass(frozen=True)
class Row:
    values: tuple[object, ...]
    scope: Scope
    agg_values: dict[int, object] | None = None
    aliases: dict[str, object] | None = None


def eval_expr(node: Node, row: Row) -> object:
    """Evaluate an expression node against a row."""
    if isinstance(node, Literal):
        return node.value
    if isinstance(node, ColumnRef):
        return resolve_column(node, row)
    if isinstance(node, UnaryOp):
        return negate(eval_expr(node.operand, row))
    if isinstance(node, BinaryOp):
        return _eval_binary(node, row)
    if isinstance(node, NotOp):
        return not_(_as_logic(eval_expr(node.operand, row)))
    if isinstance(node, IsNull):
        is_null = eval_expr(node.operand, row) is None
        return (not is_null) if node.negated else is_null
    if isinstance(node, FuncCall):
        return _eval_call(node, row)
    raise TypeMismatchError(f"cannot evaluate {node!r}")


def resolve_column(ref: ColumnRef, row: Row) -> object:
    """Resolve a column reference against aliases (ORDER BY) then the scope."""
    if ref.table is None and row.aliases is not None and ref.name in row.aliases:
        return row.aliases[ref.name]
    entries = row.scope.entries
    if ref.table is not None:
        if ref.table not in {t for t, _ in entries}:
            raise UnknownTableError(f"unknown table {ref.table!r}")
        for i, (t, c) in enumerate(entries):
            if t == ref.table and c == ref.name:
                return row.values[i]
        raise UnknownColumnError(f"unknown column {ref.table}.{ref.name}")
    matches = [i for i, (_, c) in enumerate(entries) if c == ref.name]
    if not matches:
        raise UnknownColumnError(f"unknown column {ref.name!r}")
    if len(matches) > 1:
        raise AmbiguousColumnError(f"ambiguous column {ref.name!r}")
    return row.values[matches[0]]


def require_logic(v: object) -> bool | None:
    """Coerce a value to a logical one; non-booleans raise TypeMismatchError."""
    if v is None or isinstance(v, bool):
        return v
    raise TypeMismatchError(f"expected a logical value, got {type_of(v)}")


_as_logic = require_logic


def _eval_binary(node: BinaryOp, row: Row) -> object:
    op = node.op
    if op == "AND":
        return and_(
            _as_logic(eval_expr(node.left, row)),
            _as_logic(eval_expr(node.right, row)),
        )
    if op == "OR":
        return or_(
            _as_logic(eval_expr(node.left, row)),
            _as_logic(eval_expr(node.right, row)),
        )
    a = eval_expr(node.left, row)
    b = eval_expr(node.right, row)
    if op in ("+", "-", "*", "/", "%"):
        return arith(op, a, b)
    return _compare(op, a, b)


def _compare(op: str, a: object, b: object) -> bool | None:
    if op == "=":
        return compare_eq(a, b)
    if op == "<>":
        r = compare_eq(a, b)
        return None if r is None else not r
    if op == "<":
        return compare_lt(a, b)
    if op == ">":
        return compare_lt(b, a)
    if op == "<=":
        r = compare_lt(b, a)
        return None if r is None else not r
    # op == ">="
    r = compare_lt(a, b)
    return None if r is None else not r


def _eval_call(node: FuncCall, row: Row) -> object:
    if is_aggregate_name(node.name):
        if row.agg_values is not None and id(node) in row.agg_values:
            return row.agg_values[id(node)]
        raise AggregateError(
            f"aggregate {node.name} is not allowed in this context")
    args = [eval_expr(a, row) for a in node.args]
    return call_scalar(node.name, args)


# ---------------------------------------------------------------------------
# Scalar functions
# ---------------------------------------------------------------------------

def call_scalar(name: str, args: list[object]) -> object:
    """Call a scalar function by (case-insensitive) name."""
    lower = name.lower()
    if lower == "concat":
        _arity(name, args, at_least=2)
        return _concat(args)
    if lower == "upper":
        _arity(name, args, exactly=1)
        return None if args[0] is None else _text(name, args[0]).upper()
    if lower == "lower":
        _arity(name, args, exactly=1)
        return None if args[0] is None else _text(name, args[0]).lower()
    if lower == "length":
        _arity(name, args, exactly=1)
        return None if args[0] is None else len(_text(name, args[0]))
    if lower == "abs":
        _arity(name, args, exactly=1)
        return _abs(name, args[0])
    if lower == "coalesce":
        _arity(name, args, at_least=1)
        for a in args:
            if a is not None:
                return a
        return None
    raise UnknownFunctionError(f"unknown function {name!r}")


def _arity(name: str, args: list[object],
           exactly: int | None = None, at_least: int | None = None) -> None:
    n = len(args)
    if exactly is not None and n != exactly:
        raise ArityError(f"{name} expects {exactly} argument(s), got {n}")
    if at_least is not None and n < at_least:
        raise ArityError(
            f"{name} expects at least {at_least} arguments, got {n}")


def _text(fname: str, v: object) -> str:
    if not isinstance(v, str):
        raise TypeMismatchError(f"{fname} expects TEXT, got {type_of(v)}")
    return v


def _concat(args: list[object]) -> object:
    parts: list[str] = []
    for a in args:
        if a is None:
            return None  # concat is NULL if any argument is NULL
        if not isinstance(a, str):
            raise TypeMismatchError(f"concat expects TEXT, got {type_of(a)}")
        parts.append(a)
    return "".join(parts)


def _abs(fname: str, v: object) -> object:
    if v is None:
        return None
    if not is_numeric(v):
        raise TypeMismatchError(f"{fname} expects a number, got {type_of(v)}")
    return abs(v)  # type: ignore[arg-type]  # preserves INT vs FLOAT
