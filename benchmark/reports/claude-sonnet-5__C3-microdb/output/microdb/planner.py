"""Planner: Query -> Plan, performing structural (schema-independent) validation."""

from __future__ import annotations

import dataclasses

from microdb.errors import AggregateError, GroupingError
from microdb.expr import contains_aggregate, expr_equal
from microdb.parser import BinOp, ColumnRef, FuncCall, IsNull, Query, Star, UnaryOp


@dataclasses.dataclass(frozen=True)
class Stage:
    name: str
    data: object


@dataclasses.dataclass(frozen=True)
class Plan:
    query: Query
    stages: list

    def __iter__(self):
        return iter(self.stages)

    def __len__(self) -> int:
        return len(self.stages)

    def __getitem__(self, i: int) -> Stage:
        return self.stages[i]


def _validate_no_aggregate(expr: object, clause: str) -> None:
    if expr is not None and contains_aggregate(expr):
        raise AggregateError(f"aggregate functions are not allowed in {clause}")


def _validate_group_item(expr: object, group_by_exprs: list) -> None:
    """Recursively ensure every leaf of expr is covered by an aggregate or a grouping expr."""
    if any(expr_equal(expr, g) for g in group_by_exprs):
        return
    if isinstance(expr, FuncCall) and expr.name.upper() in {"COUNT", "SUM", "AVG", "MIN", "MAX"}:
        return
    if isinstance(expr, ColumnRef):
        raise GroupingError(f"column {expr.name!r} is neither aggregated nor grouped")
    if isinstance(expr, UnaryOp):
        _validate_group_item(expr.operand, group_by_exprs)
        return
    if isinstance(expr, BinOp):
        _validate_group_item(expr.left, group_by_exprs)
        _validate_group_item(expr.right, group_by_exprs)
        return
    if isinstance(expr, IsNull):
        _validate_group_item(expr.expr, group_by_exprs)
        return
    if isinstance(expr, FuncCall):
        for a in expr.args:
            _validate_group_item(a, group_by_exprs)
        return
    # Literal or anything else: constants are always fine.


def plan(query: Query) -> Plan:
    """Validate a Query and build an inspectable Plan of stages."""
    _validate_no_aggregate(query.where, "WHERE")
    if query.join is not None:
        _validate_no_aggregate(query.join.on, "ON")
    for g in query.group_by:
        _validate_no_aggregate(g, "GROUP BY")

    has_aggregate = any(contains_aggregate(item.expr) for item in query.select_items if not isinstance(item.expr, Star))
    has_aggregate = has_aggregate or (query.having is not None and contains_aggregate(query.having))
    grouping_active = bool(query.group_by) or has_aggregate

    if grouping_active:
        for item in query.select_items:
            if isinstance(item.expr, Star):
                raise GroupingError("'*' is not allowed with GROUP BY or aggregates")
            _validate_group_item(item.expr, query.group_by)

    stages = [Stage("from", query.from_table)]
    if query.join is not None:
        stages.append(Stage("join", query.join))
    if query.where is not None:
        stages.append(Stage("where", query.where))
    if grouping_active:
        stages.append(Stage("group_by", query.group_by))
        stages.append(Stage("aggregate", has_aggregate))
    if query.having is not None:
        stages.append(Stage("having", query.having))
    stages.append(Stage("select", (query.select_items, query.distinct)))
    if query.distinct:
        stages.append(Stage("distinct", True))
    if query.order_by:
        stages.append(Stage("order_by", query.order_by))
    if query.offset is not None:
        stages.append(Stage("offset", query.offset))
    if query.limit is not None:
        stages.append(Stage("limit", query.limit))
    return Plan(query, stages)
