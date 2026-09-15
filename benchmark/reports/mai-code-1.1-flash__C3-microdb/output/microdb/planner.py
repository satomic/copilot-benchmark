from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .expr import contains_aggregate
from .parser import Query, SelectItem


@dataclass(frozen=True)
class FromStage:
    table: str


@dataclass(frozen=True)
class JoinStage:
    table: str
    kind: str
    on: Any


@dataclass(frozen=True)
class WhereStage:
    predicate: Any


@dataclass(frozen=True)
class GroupStage:
    keys: list[Any]
    select_items: list[SelectItem]
    having: Any | None
    aggregate_needed: bool


@dataclass(frozen=True)
class SelectStage:
    items: list[SelectItem]


@dataclass(frozen=True)
class DistinctStage:
    pass


@dataclass(frozen=True)
class OrderStage:
    items: list[tuple[Any, str]]


@dataclass(frozen=True)
class LimitStage:
    offset: int | None
    limit: int | None


Plan = tuple[Any, ...]


def plan(query: Query) -> Plan:
    stages: list[Any] = [FromStage(query.from_table)]
    if query.join is not None:
        stages.append(JoinStage(query.join.table, query.join.kind, query.join.on))
    if query.where is not None:
        stages.append(WhereStage(query.where))
    needed = any(contains_aggregate(item.expr) for item in query.select_items) or (query.having is not None and contains_aggregate(query.having))
    if query.group_by or needed:
        stages.append(GroupStage(query.group_by, query.select_items, query.having, needed))
    if query.select_items:
        stages.append(SelectStage(query.select_items))
    if query.distinct:
        stages.append(DistinctStage())
    if query.order_by:
        stages.append(OrderStage(query.order_by))
    stages.append(LimitStage(query.offset, query.limit))
    return tuple(stages)
