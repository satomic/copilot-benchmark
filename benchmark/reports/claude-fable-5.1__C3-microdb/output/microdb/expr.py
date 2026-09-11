"""Expression evaluation against a row scope."""

from __future__ import annotations

import dataclasses
from typing import Callable, Optional

from . import value as V
from .errors import (
    AggregateError,
    AmbiguousColumnError,
    ArityError,
    TypeMismatchError,
    UnknownColumnError,
    UnknownFunctionError,
    UnknownTableError,
)
from .parser import BinaryOp, ColumnRef, Expr, FuncCall, IsNull, Literal, UnaryOp

# --- scopes -------------------------------------------------------------------


class Scope:
    """Names the positions of a working row.

    ``columns`` holds ``(table, name)`` pairs. The first ``priority`` entries are
    output aliases: an unqualified lookup checks them first and the first match
    wins, so an alias shadows a same-named input column (section 8.3 rule 5).
    """

    def __init__(self, columns: list[tuple[Optional[str], str]], priority: int = 0) -> None:
        self.columns = list(columns)
        self.priority = priority
        self.tables = {t for t, _ in columns if t is not None}
        self._cache: dict[tuple[Optional[str], str], int] = {}

    def __len__(self) -> int:
        return len(self.columns)

    def resolve(self, table: Optional[str], name: str) -> int:
        key = (table, name)
        if key not in self._cache:
            self._cache[key] = self._resolve(table, name)
        return self._cache[key]

    def _resolve(self, table: Optional[str], name: str) -> int:
        if table is not None:
            if table not in self.tables:
                raise UnknownTableError(f"unknown table {table!r}")
            for i, (t, n) in enumerate(self.columns):
                if t == table and n == name:
                    return i
            raise UnknownColumnError(f"unknown column {table}.{name}")
        for i in range(self.priority):
            if self.columns[i][1] == name:
                return i
        matches = [i for i in range(self.priority, len(self.columns)) if self.columns[i][1] == name]
        if not matches:
            raise UnknownColumnError(f"unknown column {name!r}")
        if len(matches) > 1:
            raise AmbiguousColumnError(f"column {name!r} is ambiguous")
        return matches[0]

    def extend(self, other: "Scope") -> "Scope":
        """Prefix this scope's columns as priority (alias) columns before ``other``."""
        return Scope(self.columns + other.columns, priority=len(self.columns))


@dataclasses.dataclass
class Context:
    """Everything an expression may read: the row, its scope and aggregate results."""

    scope: Scope
    row: list[object]
    aggregates: Optional[dict[tuple, object]] = None


# --- scalar functions ---------------------------------------------------------


def _text_arg(fname: str, v: object) -> Optional[str]:
    if v is None or isinstance(v, str):
        return v
    raise TypeMismatchError(f"{fname} requires TEXT, got {V.type_of(v)}")


def _fn_upper(args: list[object]) -> object:
    s = _text_arg("upper", args[0])
    return None if s is None else s.upper()


def _fn_lower(args: list[object]) -> object:
    s = _text_arg("lower", args[0])
    return None if s is None else s.lower()


def _fn_length(args: list[object]) -> object:
    s = _text_arg("length", args[0])
    return None if s is None else len(s)


def _fn_abs(args: list[object]) -> object:
    v = args[0]
    if v is None:
        return None
    if not V.is_numeric(v):
        raise TypeMismatchError(f"abs requires numeric input, got {V.type_of(v)}")
    return abs(v)  # type: ignore[arg-type]


def _fn_coalesce(args: list[object]) -> object:
    for v in args:
        if v is not None:
            return v
    return None


def _fn_concat(args: list[object]) -> object:
    return V.concat(*args)


# name -> (min arity, max arity or None, implementation)
SCALAR_FUNCTIONS: dict[str, tuple[int, Optional[int], Callable[[list[object]], object]]] = {
    "concat": (2, None, _fn_concat),
    "upper": (1, 1, _fn_upper),
    "lower": (1, 1, _fn_lower),
    "length": (1, 1, _fn_length),
    "abs": (1, 1, _fn_abs),
    "coalesce": (1, None, _fn_coalesce),
}


def call_scalar(name: str, args: list[object]) -> object:
    spec = SCALAR_FUNCTIONS.get(name.lower())
    if spec is None:
        raise UnknownFunctionError(f"unknown function {name!r}")
    lo, hi, impl = spec
    n = len(args)
    if n < lo or (hi is not None and n > hi):
        expected = str(lo) if hi == lo else (f"at least {lo}" if hi is None else f"{lo}..{hi}")
        raise ArityError(f"{name} expects {expected} argument(s), got {n}")
    return impl(args)


# --- evaluation ---------------------------------------------------------------


def _logical(op: str, v: object) -> Optional[bool]:
    if not V.is_logical(v):
        raise TypeMismatchError(f"{op} requires BOOL operands, got {V.type_of(v)}")
    return v  # type: ignore[return-value]


def _compare(op: str, a: object, b: object) -> Optional[bool]:
    if op == "=":
        return V.compare_eq(a, b)
    if op == "<>":
        return V.not_(V.compare_eq(a, b))
    if op == "<":
        return V.compare_lt(a, b)
    if op == ">":
        return V.compare_lt(b, a)
    if op == "<=":
        return V.or_(V.compare_lt(a, b), V.compare_eq(a, b))
    return V.or_(V.compare_lt(b, a), V.compare_eq(a, b))


def _eval_binary(node: BinaryOp, ctx: Context) -> object:
    op = node.op
    if op == "AND":
        a = _logical("AND", evaluate(node.left, ctx))
        b = _logical("AND", evaluate(node.right, ctx))
        return V.and_(a, b)
    if op == "OR":
        a = _logical("OR", evaluate(node.left, ctx))
        b = _logical("OR", evaluate(node.right, ctx))
        return V.or_(a, b)
    left = evaluate(node.left, ctx)
    right = evaluate(node.right, ctx)
    if op in ("=", "<>", "<", "<=", ">", ">="):
        return _compare(op, left, right)
    return V.arith(op, left, right)


def evaluate(node: Expr, ctx: Context) -> object:
    if isinstance(node, Literal):
        return node.value
    if isinstance(node, ColumnRef):
        return ctx.row[ctx.scope.resolve(node.table, node.name)]
    if isinstance(node, BinaryOp):
        return _eval_binary(node, ctx)
    if isinstance(node, UnaryOp):
        v = evaluate(node.operand, ctx)
        if node.op == "NOT":
            return V.not_(_logical("NOT", v))
        return V.negate(v)
    if isinstance(node, IsNull):
        v = evaluate(node.operand, ctx)
        return (v is not None) if node.negated else (v is None)
    if isinstance(node, FuncCall):
        if node.is_aggregate:
            if ctx.aggregates is None:
                raise AggregateError(f"aggregate {node.name}() is not allowed here")
            return ctx.aggregates[expr_key(node)]
        return call_scalar(node.name, [evaluate(a, ctx) for a in node.args])
    raise TypeError(f"unknown expression node {node!r}")


def eval_predicate(node: Expr, ctx: Context, clause: str) -> bool:
    """True only when the predicate evaluates to TRUE; UNKNOWN and FALSE drop."""
    v = evaluate(node, ctx)
    if not V.is_logical(v):
        raise TypeMismatchError(f"{clause} predicate must be BOOL, got {V.type_of(v)}")
    return v is True


# --- structural helpers -------------------------------------------------------


def expr_key(node: Expr) -> tuple:
    """Hashable structural identity of an expression (case-folded function names)."""
    if isinstance(node, Literal):
        return ("lit", V.type_of(node.value), node.value)
    if isinstance(node, ColumnRef):
        return ("col", node.table, node.name)
    if isinstance(node, BinaryOp):
        return ("bin", node.op, expr_key(node.left), expr_key(node.right))
    if isinstance(node, UnaryOp):
        return ("un", node.op, expr_key(node.operand))
    if isinstance(node, IsNull):
        return ("isnull", node.negated, expr_key(node.operand))
    if isinstance(node, FuncCall):
        return ("fn", node.name, node.star, tuple(expr_key(a) for a in node.args))
    raise TypeError(f"unknown expression node {node!r}")


def children(node: Expr) -> tuple[Expr, ...]:
    if isinstance(node, BinaryOp):
        return (node.left, node.right)
    if isinstance(node, (UnaryOp, IsNull)):
        return (node.operand,)
    if isinstance(node, FuncCall):
        return node.args
    return ()


def find_aggregates(node: Expr, out: list[FuncCall]) -> None:
    """Append every aggregate call in ``node`` to ``out`` (pre-order, with duplicates)."""
    if isinstance(node, FuncCall) and node.is_aggregate:
        out.append(node)
        return
    for child in children(node):
        find_aggregates(child, out)


def has_aggregate(node: Expr) -> bool:
    found: list[FuncCall] = []
    find_aggregates(node, found)
    return bool(found)


def references_columns(node: Expr) -> bool:
    if isinstance(node, ColumnRef):
        return True
    return any(references_columns(c) for c in children(node))
