"""Turn a Query into an inspectable pipeline of named stages."""

from __future__ import annotations

import dataclasses
from collections.abc import Iterator

from microdb.expr import collect_aggregates
from microdb.parser import Expr, FuncCall, OrderItem, Query, SelectItem

# Stages follow section 8: scan, join, where, group, aggregate, having,
# project, distinct, order, offset, limit.


@dataclasses.dataclass(frozen=True)
class Scan:
    table: str


@dataclasses.dataclass(frozen=True)
class Join:
    kind: str
    table: str
    on: Expr


@dataclasses.dataclass(frozen=True)
class Where:
    predicate: Expr


@dataclasses.dataclass(frozen=True)
class GroupBy:
    keys: tuple[Expr, ...]
    implicit: bool


@dataclasses.dataclass(frozen=True)
class Aggregate:
    calls: tuple[FuncCall, ...]


@dataclasses.dataclass(frozen=True)
class Having:
    predicate: Expr


@dataclasses.dataclass(frozen=True)
class Project:
    items: tuple[SelectItem, ...]


@dataclasses.dataclass(frozen=True)
class Distinct:
    pass


@dataclasses.dataclass(frozen=True)
class OrderBy:
    items: tuple[OrderItem, ...]


@dataclasses.dataclass(frozen=True)
class Offset:
    count: int


@dataclasses.dataclass(frozen=True)
class Limit:
    count: int


@dataclasses.dataclass(frozen=True)
class Plan:
    """A sequence of named stage objects."""

    stages: tuple[object, ...]

    def __iter__(self) -> Iterator[object]:
        return iter(self.stages)

    def __len__(self) -> int:
        return len(self.stages)

    def __getitem__(self, index: int) -> object:
        return self.stages[index]


def plan(query: Query) -> Plan:
    """Build a pipeline. Does not touch tables or evaluate expressions."""
    stages: list[object] = [Scan(query.table)]
    _add_join(stages, query)
    if query.where is not None:
        stages.append(Where(query.where))
    _add_grouping(stages, query)
    if query.having is not None:
        stages.append(Having(query.having))
    stages.append(Project(query.items))
    if query.distinct:
        stages.append(Distinct())
    if query.order_by:
        stages.append(OrderBy(query.order_by))
    if query.offset is not None:
        stages.append(Offset(query.offset))
    if query.limit is not None:
        stages.append(Limit(query.limit))
    return Plan(tuple(stages))


def _add_join(stages: list[object], query: Query) -> None:
    if query.join is None:
        return
    stages.append(Join(query.join.kind, query.join.table, query.join.on))


def _add_grouping(stages: list[object], query: Query) -> None:
    select_having = _select_having_aggs(query)
    if not query.group_by and not select_having:
        return
    calls = list(select_having)
    for item in query.order_by:
        collect_aggregates(item.expr, calls)
    implicit = not bool(query.group_by)
    stages.append(GroupBy(query.group_by, implicit))
    stages.append(Aggregate(tuple(calls)))


def _select_having_aggs(query: Query) -> list[FuncCall]:
    found: list[FuncCall] = []
    for item in query.items:
        if item.expr is not None:
            collect_aggregates(item.expr, found)
    if query.having is not None:
        collect_aggregates(query.having, found)
    return found
