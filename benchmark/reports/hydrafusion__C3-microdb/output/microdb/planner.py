from collections.abc import Iterator, Sequence
from dataclasses import dataclass

from .expr import contains_aggregate
from .parser import Query


@dataclass(frozen=True)
class Stage:
    name: str


@dataclass(frozen=True)
class FromStage(Stage):
    table: str


@dataclass(frozen=True)
class JoinStage(Stage):
    kind: str
    table: str


@dataclass(frozen=True)
class Plan(Sequence[Stage]):
    query: Query
    stages: tuple[Stage, ...]

    def __getitem__(self, index: int | slice) -> Stage | tuple[Stage, ...]:
        return self.stages[index]

    def __len__(self) -> int:
        return len(self.stages)

    def __iter__(self) -> Iterator[Stage]:
        return iter(self.stages)


def plan(query: Query) -> Plan:
    stages: list[Stage] = [FromStage("FROM", query.table)]
    if query.join:
        stages.append(JoinStage("JOIN", query.join.kind, query.join.table))
    if query.where:
        stages.append(Stage("WHERE"))
    if query.group_by:
        stages.append(Stage("GROUP BY"))
    if query.group_by or any(
        contains_aggregate(item.expression) for item in query.select
    ) or (query.having is not None and contains_aggregate(query.having)):
        stages.append(Stage("AGGREGATE"))
    if query.having:
        stages.append(Stage("HAVING"))
    stages.append(Stage("SELECT"))
    if query.distinct:
        stages.append(Stage("DISTINCT"))
    if query.order_by:
        stages.append(Stage("ORDER BY"))
    if query.offset:
        stages.append(Stage("OFFSET"))
    if query.limit is not None:
        stages.append(Stage("LIMIT"))
    return Plan(query, tuple(stages))
