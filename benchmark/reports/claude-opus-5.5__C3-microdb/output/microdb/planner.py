"""Planner: turns a Query into an inspectable pipeline of named stages."""

from __future__ import annotations

import dataclasses
from collections.abc import Sequence
from typing import Iterator, overload

from .errors import AggregateError
from .expr import contains_aggregate
from .parser import Expr, JoinClause, OrderItem, Query, SelectItem


@dataclasses.dataclass(frozen=True)
class Stage:
    """Base class of plan stages; every stage has a ``name``."""

    @property
    def name(self) -> str:
        return "stage"


@dataclasses.dataclass(frozen=True)
class ScanStage(Stage):
    table: str

    @property
    def name(self) -> str:
        return "scan"


@dataclasses.dataclass(frozen=True)
class JoinStage(Stage):
    kind: str
    table: str
    on: Expr

    @property
    def name(self) -> str:
        return "join"


@dataclasses.dataclass(frozen=True)
class FilterStage(Stage):
    predicate: Expr

    @property
    def name(self) -> str:
        return "filter"


@dataclasses.dataclass(frozen=True)
class GroupStage(Stage):
    keys: tuple  # empty for the implicit whole-input group

    @property
    def name(self) -> str:
        return "group"


@dataclasses.dataclass(frozen=True)
class AggregateStage(Stage):
    @property
    def name(self) -> str:
        return "aggregate"


@dataclasses.dataclass(frozen=True)
class HavingStage(Stage):
    predicate: Expr

    @property
    def name(self) -> str:
        return "having"


@dataclasses.dataclass(frozen=True)
class ProjectStage(Stage):
    items: tuple

    @property
    def name(self) -> str:
        return "project"


@dataclasses.dataclass(frozen=True)
class DistinctStage(Stage):
    @property
    def name(self) -> str:
        return "distinct"


@dataclasses.dataclass(frozen=True)
class SortStage(Stage):
    keys: tuple  # of OrderItem

    @property
    def name(self) -> str:
        return "sort"


@dataclasses.dataclass(frozen=True)
class OffsetStage(Stage):
    count: int

    @property
    def name(self) -> str:
        return "offset"


@dataclasses.dataclass(frozen=True)
class LimitStage(Stage):
    count: int

    @property
    def name(self) -> str:
        return "limit"


class Plan(Sequence):
    """An ordered, immutable sequence of stages, plus the source query."""

    def __init__(self, stages: list[Stage], query: Query) -> None:
        self._stages = tuple(stages)
        self.query = query

    @overload
    def __getitem__(self, index: int) -> Stage: ...

    @overload
    def __getitem__(self, index: slice) -> tuple: ...

    def __getitem__(self, index: int | slice) -> Stage | tuple:
        return self._stages[index]

    def __len__(self) -> int:
        return len(self._stages)

    def __iter__(self) -> Iterator[Stage]:
        return iter(self._stages)

    @property
    def names(self) -> list[str]:
        return [s.name for s in self._stages]

    def find(self, stage_type: type) -> Stage | None:
        """Return the first stage of the given type, or None."""
        for stage in self._stages:
            if isinstance(stage, stage_type):
                return stage
        return None

    def __repr__(self) -> str:
        return f"Plan({' -> '.join(self.names)})"


def _is_grouped(query: Query) -> bool:
    # HAVING without GROUP BY makes the whole input one group, as in standard SQL.
    if query.group_by or query.having is not None:
        return True
    return any(contains_aggregate(item.expr) for item in query.items)


def _validate(query: Query) -> None:
    if query.join is not None and contains_aggregate(query.join.on):
        raise AggregateError("aggregates are not allowed in JOIN ... ON")
    if contains_aggregate(query.where):
        raise AggregateError("aggregates are not allowed in WHERE")
    if any(contains_aggregate(k) for k in query.group_by):
        raise AggregateError("aggregates are not allowed in GROUP BY")
    if not _is_grouped(query):
        if any(contains_aggregate(o.expr) for o in query.order_by):
            raise AggregateError("aggregates in ORDER BY require grouping")


def plan(query: Query) -> Plan:
    """Build the execution pipeline for a parsed query."""
    _validate(query)
    stages: list[Stage] = [ScanStage(query.table)]
    join: JoinClause | None = query.join
    if join is not None:
        stages.append(JoinStage(join.kind, join.table, join.on))
    if query.where is not None:
        stages.append(FilterStage(query.where))
    if _is_grouped(query):
        stages.append(GroupStage(tuple(query.group_by)))
        stages.append(AggregateStage())
        if query.having is not None:
            stages.append(HavingStage(query.having))
    items: tuple[SelectItem, ...] = query.items
    stages.append(ProjectStage(items))
    if query.distinct:
        stages.append(DistinctStage())
    if query.order_by:
        order: tuple[OrderItem, ...] = query.order_by
        stages.append(SortStage(order))
    if query.offset is not None:
        stages.append(OffsetStage(query.offset))
    if query.limit is not None:
        stages.append(LimitStage(query.limit))
    return Plan(stages, query)
