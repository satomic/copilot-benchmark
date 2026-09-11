"""An inspectable, ordered sequence of execution stages."""

from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from typing import overload

from .errors import AggregateError
from .expr import Call, Expr, children, has_aggregate, validate_call
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


def is_grouped(query: Query) -> bool:
    return bool(query.group_by) or any(
        has_aggregate(expr) for expr in
        [*(item.expr for item in query.select),
         *([query.having] if query.having is not None else [])])


def _validate(expr: Expr) -> None:
    if isinstance(expr, Call):
        validate_call(expr)
    for child in children(expr):
        _validate(child)


def _validate_query(query: Query) -> None:
    restricted = [("WHERE", query.where),
                  ("ON", query.join.on if query.join else None)]
    restricted.extend(("GROUP BY", expr) for expr in query.group_by)
    for clause, expr in restricted:
        if expr is not None and has_aggregate(expr):
            raise AggregateError(f"Aggregates are not allowed in {clause}")
    expressions = [*(item.expr for item in query.select), *query.group_by,
                   *(item.expr for item in query.order_by)]
    expressions.extend(expr for _, expr in restricted if expr is not None)
    if query.having is not None:
        expressions.append(query.having)
    for expr in expressions:
        _validate(expr)
    if not is_grouped(query) and any(has_aggregate(item.expr) for item in query.order_by):
        raise AggregateError("ORDER BY aggregates require a grouped query")


def plan(query: Query) -> Plan:
    _validate_query(query)
    stages = [Stage("FROM")]
    if query.join:
        stages.append(Stage("JOIN"))
    if query.where is not None:
        stages.append(Stage("WHERE"))
    if query.group_by:
        stages.append(Stage("GROUP BY"))
    if is_grouped(query):
        stages.append(Stage("AGGREGATE"))
    if query.having is not None:
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
