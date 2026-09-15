"""Query planner and plan representation."""

from __future__ import annotations

from collections.abc import Iterator, Sequence
import dataclasses
from typing import Any
from microdb.errors import AggregateError
from microdb.expr import AggregateCall, Expr, Literal, find_aggregates
from microdb.parser import JoinClause, OrderItem, Query, SelectItem


@dataclasses.dataclass(frozen=True)
class Stage:
    """Base stage in a query plan."""

    name: str


@dataclasses.dataclass(frozen=True)
class FromStage(Stage):
    table: str = ""


@dataclasses.dataclass(frozen=True)
class JoinStage(Stage):
    join_type: str = "INNER"
    table: str = ""
    on: Expr = dataclasses.field(default_factory=lambda: Literal(None))


@dataclasses.dataclass(frozen=True)
class WhereStage(Stage):
    predicate: Expr = dataclasses.field(default_factory=lambda: Literal(None))


@dataclasses.dataclass(frozen=True)
class GroupByStage(Stage):
    exprs: list[Expr] = dataclasses.field(default_factory=list)


@dataclasses.dataclass(frozen=True)
class AggregateStage(Stage):
    aggregates: list[AggregateCall] = dataclasses.field(default_factory=list)


@dataclasses.dataclass(frozen=True)
class HavingStage(Stage):
    predicate: Expr = dataclasses.field(default_factory=lambda: Literal(None))


@dataclasses.dataclass(frozen=True)
class SelectStage(Stage):
    items: list[SelectItem] = dataclasses.field(default_factory=list)


@dataclasses.dataclass(frozen=True)
class DistinctStage(Stage):
    pass


@dataclasses.dataclass(frozen=True)
class OrderByStage(Stage):
    items: list[OrderItem] = dataclasses.field(default_factory=list)


@dataclasses.dataclass(frozen=True)
class SliceStage(Stage):
    offset: int | None = None
    limit: int | None = None


class Plan(Sequence[Stage]):
    """Sequence of plan stages."""

    def __init__(self, stages: list[Stage], query: Query) -> None:
        self._stages: list[Stage] = list(stages)
        self.query: Query = query

    def __len__(self) -> int:
        return len(self._stages)

    def __getitem__(self, index: Any) -> Any:
        return self._stages[index]

    def __iter__(self) -> Iterator[Stage]:
        return iter(self._stages)


def _collect_aggregates(query: Query) -> list[AggregateCall]:
    aggs: list[AggregateCall] = []
    for item in query.select_items:
        if item.expr is not None:
            aggs.extend(find_aggregates(item.expr))
    if query.having is not None:
        aggs.extend(find_aggregates(query.having))
    for order in query.order_by:
        aggs.extend(find_aggregates(order.expr))
    return list(dict.fromkeys(aggs))


def plan(query: Query) -> Plan:
    """Construct an execution plan from a parsed Query AST."""
    stages: list[Stage] = [FromStage(name="FROM", table=query.from_table)]
    if query.join is not None:
        if find_aggregates(query.join.on):
            raise AggregateError("ON clause cannot contain aggregate functions")
        stages.append(
            JoinStage(
                name="JOIN",
                join_type=query.join.type,
                table=query.join.table,
                on=query.join.on,
            )
        )
    if query.where is not None:
        if find_aggregates(query.where):
            raise AggregateError("WHERE clause cannot contain aggregate functions")
        stages.append(WhereStage(name="WHERE", predicate=query.where))
    aggs = _collect_aggregates(query)
    if query.group_by or aggs or query.having is not None:
        stages.append(GroupByStage(name="GROUP BY", exprs=query.group_by))
        stages.append(AggregateStage(name="AGGREGATE", aggregates=aggs))
    if query.having is not None:
        stages.append(HavingStage(name="HAVING", predicate=query.having))
    stages.append(SelectStage(name="SELECT", items=query.select_items))
    if query.distinct:
        stages.append(DistinctStage(name="DISTINCT"))
    if query.order_by:
        stages.append(OrderByStage(name="ORDER BY", items=query.order_by))
    if query.offset is not None or query.limit is not None:
        stages.append(
            SliceStage(name="SLICE", offset=query.offset, limit=query.limit)
        )
    return Plan(stages, query)
