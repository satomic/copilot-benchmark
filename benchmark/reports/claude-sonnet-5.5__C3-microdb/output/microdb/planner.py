"""Planner: Query -> Plan (an inspectable sequence of named stages)."""

import dataclasses
from collections.abc import Sequence
from typing import Iterator, overload

from .expr import contains_aggregate
from .parser import Query, Star


@dataclasses.dataclass(frozen=True)
class Stage:
    name: str
    payload: object = None


class Plan(Sequence):
    def __init__(self, query: Query, stages: list[Stage]) -> None:
        self.query = query
        self._stages = tuple(stages)

    @overload
    def __getitem__(self, index: int) -> Stage: ...
    @overload
    def __getitem__(self, index: slice) -> tuple[Stage, ...]: ...

    def __getitem__(self, index):  # type: ignore[no-untyped-def]
        return self._stages[index]

    def __len__(self) -> int:
        return len(self._stages)

    def __iter__(self) -> Iterator[Stage]:
        return iter(self._stages)

    @property
    def names(self) -> list[str]:
        return [s.name for s in self._stages]


def is_grouped(query: Query) -> bool:
    if query.group_by:
        return True
    exprs = [i.expr for i in query.items if not isinstance(i.expr, Star)]
    if query.having is not None:
        exprs.append(query.having)
    return any(contains_aggregate(e) for e in exprs)


def plan(query: Query) -> Plan:
    stages = [Stage("scan", query.table)]
    if query.join is not None:
        stages.append(Stage("join", query.join))
    if query.where is not None:
        stages.append(Stage("filter", query.where))
    if is_grouped(query):
        stages.append(Stage("group", query.group_by))
        stages.append(Stage("aggregate"))
    if query.having is not None:
        stages.append(Stage("having", query.having))
    stages.append(Stage("project", query.items))
    if query.distinct:
        stages.append(Stage("distinct"))
    if query.order_by:
        stages.append(Stage("sort", query.order_by))
    if query.offset is not None:
        stages.append(Stage("offset", query.offset))
    if query.limit is not None:
        stages.append(Stage("limit", query.limit))
    return Plan(query, stages)
