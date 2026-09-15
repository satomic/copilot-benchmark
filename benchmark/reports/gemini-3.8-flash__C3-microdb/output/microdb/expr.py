"""Expression AST nodes and evaluation."""

from __future__ import annotations

import dataclasses
from typing import Any, Callable
from microdb.errors import (
    AggregateError,
    ArityError,
    GroupingError,
    TypeMismatchError,
    UnknownFunctionError,
)
from microdb.value import (
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
class Expr:
    """Base class for all expression nodes."""


@dataclasses.dataclass(frozen=True)
class Literal(Expr):
    """Literal constant."""

    value: object


@dataclasses.dataclass(frozen=True)
class ColumnRef(Expr):
    """Column reference with optional table qualifier."""

    table: str | None
    column: str


@dataclasses.dataclass(frozen=True)
class UnaryOp(Expr):
    """Unary operator expression."""

    op: str
    operand: Expr


@dataclasses.dataclass(frozen=True)
class BinaryOp(Expr):
    """Binary arithmetic operator expression."""

    op: str
    left: Expr
    right: Expr


@dataclasses.dataclass(frozen=True)
class CompareOp(Expr):
    """Comparison operator expression."""

    op: str
    left: Expr
    right: Expr


@dataclasses.dataclass(frozen=True)
class IsNullOp(Expr):
    """IS NULL / IS NOT NULL predicate."""

    operand: Expr
    negated: bool


@dataclasses.dataclass(frozen=True)
class LogicalOp(Expr):
    """Logical AND / OR expression."""

    op: str
    left: Expr
    right: Expr


@dataclasses.dataclass(frozen=True)
class NotOp(Expr):
    """Logical NOT expression."""

    operand: Expr


@dataclasses.dataclass(frozen=True)
class FunctionCall(Expr):
    """Scalar function call."""

    name: str
    args: list[Expr]


@dataclasses.dataclass(frozen=True)
class AggregateCall(Expr):
    """Aggregate function call."""

    name: str
    arg: Expr | None
    is_star: bool = False


class EvalContext:
    """Abstract evaluation context for expressions."""

    def get_column(self, table: str | None, column: str) -> object:
        raise NotImplementedError

    def get_aggregate(self, call: AggregateCall) -> object:
        raise NotImplementedError

    def matches_group_key(self, expr: Expr) -> tuple[bool, object]:
        return False, None


class RowEvalContext(EvalContext):
    """Context for row-level evaluation (WHERE, ON, un-grouped SELECT)."""

    def __init__(
        self,
        row: list[object],
        resolver: Callable[[str | None, str], int],
    ) -> None:
        self._row: list[object] = row
        self._resolver: Callable[[str | None, str], int] = resolver

    def get_column(self, table: str | None, column: str) -> object:
        idx = self._resolver(table, column)
        return self._row[idx]

    def get_aggregate(self, call: AggregateCall) -> object:
        raise AggregateError(
            f"Aggregate function '{call.name}' is not allowed in this context"
        )


class GroupEvalContext(EvalContext):
    """Context for group-level evaluation (HAVING, grouped SELECT)."""

    def __init__(
        self,
        group_key_values: dict[Expr, object],
        agg_values: dict[AggregateCall, object],
    ) -> None:
        self._group_key_values: dict[Expr, object] = group_key_values
        self._agg_values: dict[AggregateCall, object] = agg_values

    def matches_group_key(self, expr: Expr) -> tuple[bool, object]:
        if expr in self._group_key_values:
            return True, self._group_key_values[expr]
        return False, None

    def get_aggregate(self, call: AggregateCall) -> object:
        if call in self._agg_values:
            return self._agg_values[call]
        raise AggregateError(f"Uncomputed aggregate: {call}")

    def get_column(self, table: str | None, column: str) -> object:
        target = ColumnRef(table, column)
        if target in self._group_key_values:
            return self._group_key_values[target]
        raise GroupingError(
            f"Column '{column}' must appear in the GROUP BY clause or be used in an aggregate function"
        )


def _eval_compare(op: str, l_val: object, r_val: object) -> bool | None:
    if op == "=":
        return compare_eq(l_val, r_val)
    if op == "<>":
        eq = compare_eq(l_val, r_val)
        return not eq if eq is not None else None
    if op == "<":
        return compare_lt(l_val, r_val)
    if op == "<=":
        if l_val is None or r_val is None:
            return None
        return compare_lt(l_val, r_val) or compare_eq(l_val, r_val)
    if op == ">":
        return compare_lt(r_val, l_val)
    if op == ">=":
        if l_val is None or r_val is None:
            return None
        return compare_lt(r_val, l_val) or compare_eq(l_val, r_val)
    raise ValueError(f"Unknown comparison operator: {op}")


def _eval_scalar_text(name: str, args: list[object]) -> object:
    if len(args) != 1:
        raise ArityError(f"Function '{name}' expects 1 argument, got {len(args)}")
    val = args[0]
    if val is None:
        return None
    if not isinstance(val, str):
        raise TypeMismatchError(f"Function '{name}' requires TEXT, got {type_of(val)}")
    if name == "upper":
        return val.upper()
    if name == "lower":
        return val.lower()
    return len(val)


def _eval_scalar_fn(name: str, args: list[object]) -> object:
    lower_name = name.lower()
    if lower_name in ("upper", "lower", "length"):
        return _eval_scalar_text(lower_name, args)
    if lower_name == "abs":
        if len(args) != 1:
            raise ArityError(f"abs expects 1 argument, got {len(args)}")
        val = args[0]
        if val is None:
            return None
        if not is_numeric(val):
            raise TypeMismatchError(f"abs requires numeric argument, got {type_of(val)}")
        return abs(val)  # type: ignore[arg-type]
    if lower_name == "concat":
        if len(args) < 2:
            raise ArityError(f"concat expects at least 2 arguments, got {len(args)}")
        for a in args:
            if a is not None and not isinstance(a, str):
                raise TypeMismatchError(f"concat requires TEXT, got {type_of(a)}")
            if a is None:
                return None
        return "".join(a for a in args)  # type: ignore[arg-type]
    if lower_name == "coalesce":
        if not args:
            raise ArityError("coalesce expects at least 1 argument, got 0")
        for a in args:
            if a is not None:
                return a
        return None
    raise UnknownFunctionError(f"Unknown function: '{name}'")


def eval_expr(expr: Expr, ctx: EvalContext) -> object:
    """Evaluate an expression AST within an evaluation context."""
    matched, val = ctx.matches_group_key(expr)
    if matched:
        return val
    if isinstance(expr, Literal):
        return expr.value
    if isinstance(expr, ColumnRef):
        return ctx.get_column(expr.table, expr.column)
    if isinstance(expr, AggregateCall):
        return ctx.get_aggregate(expr)
    if isinstance(expr, UnaryOp):
        operand_val = eval_expr(expr.operand, ctx)
        if expr.op == "-":
            return negate(operand_val)
        raise ValueError(f"Unknown unary operator: {expr.op}")
    if isinstance(expr, BinaryOp):
        return arith(expr.op, eval_expr(expr.left, ctx), eval_expr(expr.right, ctx))
    if isinstance(expr, CompareOp):
        return _eval_compare(
            expr.op, eval_expr(expr.left, ctx), eval_expr(expr.right, ctx)
        )
    if isinstance(expr, IsNullOp):
        inner_val = eval_expr(expr.operand, ctx)
        return (inner_val is not None) if expr.negated else (inner_val is None)
    if isinstance(expr, LogicalOp):
        l_res = eval_expr(expr.left, ctx)
        r_res = eval_expr(expr.right, ctx)
        return and_(l_res, r_res) if expr.op == "AND" else or_(l_res, r_res)
    if isinstance(expr, NotOp):
        return not_(eval_expr(expr.operand, ctx))
    if isinstance(expr, FunctionCall):
        evaluated_args = [eval_expr(arg, ctx) for arg in expr.args]
        return _eval_scalar_fn(expr.name, evaluated_args)
    raise TypeError(f"Unknown expression node type: {type(expr).__name__}")


def find_aggregates(expr: Expr) -> list[AggregateCall]:
    """Find all AggregateCall nodes in an expression."""
    results: list[AggregateCall] = []

    def _collect(e: Expr) -> None:
        if isinstance(e, AggregateCall):
            results.append(e)
            if e.arg is not None:
                _collect(e.arg)
        elif isinstance(e, (UnaryOp, NotOp, IsNullOp)):
            _collect(e.operand)
        elif isinstance(e, (BinaryOp, CompareOp, LogicalOp)):
            _collect(e.left)
            _collect(e.right)
        elif isinstance(e, FunctionCall):
            for a in e.args:
                _collect(a)

    _collect(expr)
    return results
