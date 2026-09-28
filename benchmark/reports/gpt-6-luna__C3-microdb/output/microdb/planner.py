from __future__ import annotations

from collections.abc import Iterator, Sequence
from dataclasses import dataclass

from .parser import Query


@dataclass(frozen=True)
class Stage:
    name: str


@dataclass(frozen=True)
class Plan(Sequence[Stage]):
    query: Query
    stages: tuple[Stage, ...]

    def __len__(self: Plan) -> int:
        return len(self.stages)

    def __getitem__(self: Plan, index: int | slice) -> Stage | tuple[Stage, ...]:
        return self.stages[index]

    def __iter__(self: Plan) -> Iterator[Stage]:
        return iter(self.stages)


def plan(query: Query) -> Plan:
    stages = ["FROM/JOIN", "WHERE", "GROUP BY", "AGGREGATE", "HAVING",
              "SELECT", "DISTINCT", "ORDER BY", "OFFSET", "LIMIT"]
    return Plan(query, tuple(Stage(name) for name in stages))
