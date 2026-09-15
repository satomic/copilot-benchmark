"""Turn a Query AST into a sequence of named plan stages."""

from __future__ import annotations

import dataclasses
from collections.abc import Iterator

from microdb.errors import AggregateError
from microdb.expr import has_aggregate
from microdb.parser import OrderItem, Query, SelectItem, Star


@dataclasses.dataclass(frozen=True)
class FromStage:
    table: str
    name: str = "from"


@dataclasses.dataclass(frozen=True)
class JoinStage:
    table: str
    kind: str
    on: object
    name: str = "join"


@dataclasses.dataclass(frozen=True)
class WhereStage:
    pred: object
    name: str = "where"


@dataclasses.dataclass(frozen=True)
class GroupStage:
    keys: tuple[object, ...]
    name: str = "group"


@dataclasses.dataclass(frozen=True)
class HavingStage:
    pred: object
    name: str = "having"


@dataclasses.dataclass(frozen=True)
class SelectStage:
    items: tuple[SelectItem, ...]
    name: str = "select"


@dataclasses.dataclass(frozen=True)
class DistinctStage:
    name: str = "distinct"


@dataclasses.dataclass(frozen=True)
class OrderStage:
    items: tuple[OrderItem, ...]
    name: str = "order"


@dataclasses.dataclass(frozen=True)
class OffsetStage:
    count: int
    name: str = "offset"


@dataclasses.dataclass(frozen=True)
class LimitStage:
    count: int
    name: str = "limit"


@dataclasses.dataclass(frozen=True)
class Plan:
    stages: tuple[object, ...]

    def __len__(self) -> int:
        return len(self.stages)

    def __getitem__(self, index: int) -> object:  # type: ignore[override]
        return self.stages[index]

    def __iter__(self) -> Iterator[object]:
        return iter(self.stages)


def plan(query: Query) -> Plan:
    stages: list[object] = [FromStage(query.from_table)]
    if query.join is not None:
        _forbid_agg(query.join.on, "ON")
        stages.append(JoinStage(query.join.table, query.join.kind, query.join.on))
    if query.where is not None:
        _forbid_agg(query.where, "WHERE")
        stages.append(WhereStage(query.where))
    grouped = bool(query.group_by) or _query_has_agg(query)
    if query.group_by:
        for key in query.group_by:
            _forbid_agg(key, "GROUP BY")
    if grouped:
        stages.append(GroupStage(tuple(query.group_by)))
    if query.having is not None:
        stages.append(HavingStage(query.having))
    stages.append(SelectStage(tuple(query.select_items)))
    if query.distinct:
        stages.append(DistinctStage())
    if query.order_by:
        stages.append(OrderStage(tuple(query.order_by)))
    if query.offset is not None:
        stages.append(OffsetStage(query.offset))
    if query.limit is not None:
        stages.append(LimitStage(query.limit))
    return Plan(tuple(stages))


def _forbid_agg(node: object, clause: str) -> None:
    if has_aggregate(node):
        raise AggregateError(f"aggregate not allowed in {clause}")


def _query_has_agg(query: Query) -> bool:
    for item in query.select_items:
        if isinstance(item.value, Star):
            continue
        if has_aggregate(item.value):
            return True
    if query.having is not None and has_aggregate(query.having):
        return True
    for item in query.order_by:
        if has_aggregate(item.expr):
            return True
    return False
