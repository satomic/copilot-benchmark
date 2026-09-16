from dataclasses import dataclass
from .parser import Query, parse


@dataclass(frozen=True)
class Stage:
    name: str


@dataclass(frozen=True)
class Plan:
    query: Query
    stages: tuple[Stage, ...]
    def __iter__(self):
        return iter(self.stages)


def plan(query: Query) -> Plan:
    names = ["from_join", "where", "group", "aggregate", "having", "select", "distinct", "order", "slice"]
    return Plan(query, tuple(Stage(n) for n in names))
