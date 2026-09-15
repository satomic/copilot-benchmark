"""Planner: turns a Query into an inspectable Plan of named stages."""

from __future__ import annotations

import dataclasses
from collections.abc import Iterator, Sequence

from .aggregate import find_aggregates
from .parser import FuncCall, Query


@dataclasses.dataclass(frozen=True)
class Stage:
    """One execution stage; ``detail`` carries the associated AST payload."""

    name: str
    detail: object = None


class Plan(Sequence[Stage]):
    """An ordered, inspectable sequence of execution stages."""

    def __init__(self, query: Query, stages: list[Stage]) -> None:
        self.query = query
        self._stages = tuple(stages)

    def __len__(self) -> int:
        return len(self._stages)

    def __getitem__(self, index: int | slice) -> Stage | tuple[Stage, ...]:
        return self._stages[index]

    def __iter__(self) -> Iterator[Stage]:
        return iter(self._stages)

    @property
    def stages(self) -> tuple[Stage, ...]:
        return self._stages

    def stage_names(self) -> list[str]:
        """The stage names in execution order."""
        return [s.name for s in self._stages]


def query_aggregates(query: Query) -> list[FuncCall]:
    """All aggregate calls in SELECT, HAVING and ORDER BY."""
    aggs: list[FuncCall] = []
    for item in query.select:
        aggs.extend(find_aggregates(item.expr))
    if query.having is not None:
        aggs.extend(find_aggregates(query.having))
    for item in query.order_by:
        aggs.extend(find_aggregates(item.expr))
    return aggs


def plan(query: Query) -> Plan:
    """Build the stage pipeline for a query, in execution order."""
    stages = [Stage("FROM", (query.from_table, query.join))]
    if query.where is not None:
        stages.append(Stage("WHERE", query.where))
    if query.group_by:
        stages.append(Stage("GROUP BY", query.group_by))
    if query.group_by or query_aggregates(query):
        stages.append(Stage("AGGREGATE"))
    if query.having is not None:
        stages.append(Stage("HAVING", query.having))
    stages.append(Stage("SELECT", query.select))
    if query.distinct:
        stages.append(Stage("DISTINCT"))
    if query.order_by:
        stages.append(Stage("ORDER BY", query.order_by))
    if query.offset is not None:
        stages.append(Stage("OFFSET", query.offset))
    if query.limit is not None:
        stages.append(Stage("LIMIT", query.limit))
    return Plan(query, stages)
