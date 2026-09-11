"""Planner: turns a parsed :class:`Query` into an inspectable pipeline of stages.

Semantic checks that do not need table data (aggregate placement, grouping
compatibility) happen here, so a caller can validate a query without executing it.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Iterator, Sequence

from .aggregate import AGGREGATES, check_arity
from .errors import AggregateError, GroupingError
from .expr import expr_key
from .parser import (
    ColumnRef,
    Expr,
    FuncCall,
    JoinClause,
    Literal,
    OrderItem,
    Query,
    SelectItem,
    Star,
    children,
    contains_aggregate,
    walk,
)


@dataclasses.dataclass(frozen=True)
class Stage:
    """Base class for pipeline stages; every stage has a ``name``."""

    name: str


@dataclasses.dataclass(frozen=True)
class ScanStage(Stage):
    table: str


@dataclasses.dataclass(frozen=True)
class JoinStage(Stage):
    kind: str
    table: str
    on: Expr


@dataclasses.dataclass(frozen=True)
class FilterStage(Stage):
    predicate: Expr


@dataclasses.dataclass(frozen=True)
class GroupStage(Stage):
    keys: tuple[Expr, ...]
    aggregates: tuple[FuncCall, ...]
    implicit: bool


@dataclasses.dataclass(frozen=True)
class HavingStage(Stage):
    predicate: Expr


@dataclasses.dataclass(frozen=True)
class ProjectStage(Stage):
    items: tuple[SelectItem, ...]


@dataclasses.dataclass(frozen=True)
class DistinctStage(Stage):
    pass


@dataclasses.dataclass(frozen=True)
class SortStage(Stage):
    keys: tuple[OrderItem, ...]
    distinct: bool


@dataclasses.dataclass(frozen=True)
class SliceStage(Stage):
    offset: int | None
    limit: int | None


@dataclasses.dataclass(frozen=True)
class Plan(Sequence[Stage]):
    """An ordered, immutable sequence of stages."""

    stages: tuple[Stage, ...]

    def __len__(self) -> int:
        return len(self.stages)

    def __getitem__(self, index: int) -> Stage:  # type: ignore[override]
        return self.stages[index]

    def __iter__(self) -> Iterator[Stage]:
        return iter(self.stages)


def collect_aggregates(expr: Expr) -> list[FuncCall]:
    """Return every aggregate call inside ``expr`` in pre-order."""
    return [
        node
        for node in walk(expr)
        if isinstance(node, FuncCall) and node.name.lower() in AGGREGATES
    ]


def _validate_aggregate_calls(expr: Expr) -> None:
    for node in collect_aggregates(expr):
        check_arity(node.name.lower(), len(node.args))
        if isinstance(node.args[0], Star) and node.name.lower() != "count":
            raise AggregateError(f"aggregate {node.name!r} does not accept '*'")


def _grouped_ok(expr: Expr, keys: set[tuple[object, ...]]) -> bool:
    """True when ``expr`` can be evaluated per group given the grouping keys."""
    if expr_key(expr) in keys:
        return True
    if isinstance(expr, FuncCall) and expr.name.lower() in AGGREGATES:
        return True
    if isinstance(expr, Literal):
        return True
    if isinstance(expr, (ColumnRef, Star)):
        return False
    subs = children(expr)
    return bool(subs) and all(_grouped_ok(sub, keys) for sub in subs)


def _check_grouped(expr: Expr, keys: set[tuple[object, ...]], where: str) -> None:
    if not _grouped_ok(expr, keys):
        raise GroupingError(
            f"{where} expression {expr.text!r} is neither an aggregate "
            f"nor a grouping expression"
        )


def _plan_source(query: Query, stages: list[Stage]) -> None:
    stages.append(ScanStage("SCAN", query.from_table))
    join: JoinClause | None = query.join
    if join is not None:
        if contains_aggregate(join.on):
            raise AggregateError("an aggregate may not appear in a JOIN condition")
        _validate_aggregate_calls(join.on)
        stages.append(JoinStage("JOIN", join.kind, join.table, join.on))


def _plan_group(query: Query, stages: list[Stage]) -> tuple[bool, set[tuple[object, ...]]]:
    """Append the grouping stage when needed and return (grouped, key set)."""
    aggregates: list[FuncCall] = []
    for item in query.select:
        aggregates.extend(collect_aggregates(item.expr))
    if query.having is not None:
        aggregates.extend(collect_aggregates(query.having))
    keys = {expr_key(k) for k in query.group_by}
    # Per 8.2.4 only SELECT and HAVING turn the query into a single implicit group,
    # but ORDER BY aggregates still have to be computed for the groups that exist.
    grouped = bool(query.group_by) or bool(aggregates)
    if not grouped:
        return False, keys
    for item in query.order_by:
        aggregates.extend(collect_aggregates(item.expr))
    unique: dict[tuple[object, ...], FuncCall] = {}
    for call in aggregates:
        unique.setdefault(expr_key(call), call)
    stages.append(
        GroupStage("GROUP", tuple(query.group_by), tuple(unique.values()),
                   not query.group_by)
    )
    return True, keys


def _plan_projection(query: Query, stages: list[Stage],
                     grouped: bool, keys: set[tuple[object, ...]]) -> None:
    # Ambiguity resolved here: with an aggregate but no GROUP BY the key set is empty,
    # so a bare column in SELECT is a GroupingError, as in standard SQL.
    for item in query.select:
        _validate_aggregate_calls(item.expr)
        if grouped:
            _check_grouped(item.expr, keys, "SELECT")
    stages.append(ProjectStage("PROJECT", query.select))
    if query.distinct:
        stages.append(DistinctStage("DISTINCT"))


def _plan_order(query: Query, stages: list[Stage]) -> None:
    for item in query.order_by:
        _validate_aggregate_calls(item.expr)
    if query.order_by:
        stages.append(SortStage("ORDER", query.order_by, query.distinct))
    if query.limit is not None or query.offset is not None:
        stages.append(SliceStage("SLICE", query.offset, query.limit))


def plan(query: Query) -> Plan:
    """Compile ``query`` into a :class:`Plan`, validating aggregate and grouping rules."""
    stages: list[Stage] = []
    _plan_source(query, stages)
    if query.where is not None:
        if contains_aggregate(query.where):
            raise AggregateError("an aggregate may not appear in WHERE")
        _validate_aggregate_calls(query.where)
        stages.append(FilterStage("WHERE", query.where))
    grouped, keys = _plan_group(query, stages)
    if query.having is not None:
        _validate_aggregate_calls(query.having)
        if not grouped:
            raise GroupingError("HAVING requires GROUP BY or an aggregate")
        if query.group_by:
            _check_grouped(query.having, keys, "HAVING")
        stages.append(HavingStage("HAVING", query.having))
    _plan_projection(query, stages, grouped, keys)
    _plan_order(query, stages)
    return Plan(tuple(stages))
