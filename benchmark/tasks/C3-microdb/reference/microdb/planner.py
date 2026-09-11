"""Turn a parsed Query into an inspectable, ordered pipeline.

The plan is deliberately just a list of named stages. Building it separately from
running it means the stage order in section 8 of the spec is stated once, as data,
instead of being implied by the control flow of the executor.
"""

from __future__ import annotations

import dataclasses

from .errors import AggregateError, GroupingError
from .parser import Call, ColumnRef, Expr, Query, SelectItem

__all__ = ["Stage", "Plan", "plan", "collect_aggregates"]


@dataclasses.dataclass(frozen=True)
class Stage:
    name: str
    payload: object = None

    def __repr__(self) -> str:
        return f"Stage({self.name})"


@dataclasses.dataclass(frozen=True)
class Plan:
    stages: tuple[Stage, ...]
    query: Query

    def __iter__(self):  # type: ignore[no-untyped-def]
        return iter(self.stages)

    def __len__(self) -> int:
        return len(self.stages)

    def __getitem__(self, index: int) -> Stage:
        return self.stages[index]

    @property
    def names(self) -> list[str]:
        return [stage.name for stage in self.stages]


def collect_aggregates(node: Expr | None, found: dict[str, Call] | None = None) -> dict[str, Call]:
    """Collect every aggregate call in a subtree, keyed by its source text."""
    found = {} if found is None else found
    if node is None:
        return found
    if isinstance(node, Call):
        if node.is_aggregate:
            found[node.source] = node
        for arg in node.args:
            collect_aggregates(arg, found)
        return found
    for field in dataclasses.fields(node):
        child = getattr(node, field.name)
        if isinstance(child, Expr):
            collect_aggregates(child, found)
    return found


def _projection_is_grouped(item: SelectItem, group_sources: set[str]) -> bool:
    """A select item is legal under GROUP BY when it is an aggregate or a group key."""
    if item.expr is None:
        return False
    if item.expr.source in group_sources:
        return True
    return not _has_bare_column(item.expr, group_sources)


def _has_bare_column(node: Expr, group_sources: set[str]) -> bool:
    """True when the subtree reads a column that is not covered by a group key."""
    if node.source in group_sources:
        return False
    if isinstance(node, Call) and node.is_aggregate:
        return False
    if isinstance(node, ColumnRef):
        return True
    for field in dataclasses.fields(node):
        child = getattr(node, field.name)
        if isinstance(child, Expr) and _has_bare_column(child, group_sources):
            return True
        if isinstance(child, tuple):
            for element in child:
                if isinstance(element, Expr) and _has_bare_column(element, group_sources):
                    return True
    return False


def _validate(query: Query, aggregates: dict[str, Call]) -> None:
    group_sources = {expr.source for expr in query.group_by}
    if query.group_by:
        for item in query.select:
            if item.expr is None:
                raise GroupingError("* is not allowed with GROUP BY")
            if not _projection_is_grouped(item, group_sources):
                raise GroupingError(
                    f"{item.expr.source} is neither an aggregate nor a grouping expression"
                )
    elif aggregates:
        for item in query.select:
            if item.expr is None:
                raise GroupingError("* is not allowed alongside an aggregate")
            if _has_bare_column(item.expr, group_sources):
                raise GroupingError(
                    f"{item.expr.source} mixes a bare column with an aggregate"
                )
    if query.having is not None and not query.group_by and not aggregates:
        raise AggregateError("HAVING requires GROUP BY or an aggregate")


def plan(query: Query) -> Plan:
    """Build the ordered pipeline for ``query``."""
    aggregates = collect_aggregates(query.having)
    for item in query.select:
        collect_aggregates(item.expr, aggregates)
    _validate(query, aggregates)

    stages: list[Stage] = [Stage("scan", query.from_table)]
    if query.join is not None:
        stages.append(Stage("join", query.join))
    if query.where is not None:
        stages.append(Stage("filter", query.where))
    grouped = bool(query.group_by) or bool(aggregates)
    if grouped:
        stages.append(Stage("group", query.group_by))
        stages.append(Stage("aggregate", aggregates))
    if query.having is not None:
        stages.append(Stage("having", query.having))
    stages.append(Stage("project", query.select))
    if query.distinct:
        stages.append(Stage("distinct"))
    if query.order_by:
        stages.append(Stage("sort", query.order_by))
    if query.offset:
        stages.append(Stage("offset", query.offset))
    if query.limit is not None:
        stages.append(Stage("limit", query.limit))
    return Plan(tuple(stages), query)

