"""Inspectable, ordered execution stages."""

from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from typing import overload

from .parser import Query


@dataclass(frozen=True)
class Stage:
    name: str


@dataclass(frozen=True)
class Plan(Sequence[Stage]):
    query: Query
    stages: tuple[Stage, ...]

    def __len__(self) -> int:
        return len(self.stages)

    @overload
    def __getitem__(self, index: int) -> Stage: ...

    @overload
    def __getitem__(self, index: slice) -> tuple[Stage, ...]: ...

    def __getitem__(self, index: int | slice) -> Stage | tuple[Stage, ...]:
        return self.stages[index]

    def __iter__(self) -> Iterator[Stage]:
        return iter(self.stages)


def plan(query: Query) -> Plan:
    names = ["FROM"]
    if query.join:
        names.append("JOIN")
    names.extend(("WHERE", "GROUP BY", "AGGREGATE", "HAVING", "SELECT",
                  "DISTINCT", "ORDER BY", "OFFSET", "LIMIT"))
    return Plan(query, tuple(Stage(name) for name in names))
