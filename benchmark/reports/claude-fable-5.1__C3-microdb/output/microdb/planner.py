"""Turn a parsed Query into an inspectable sequence of pipeline stages."""

from __future__ import annotations

import dataclasses
from typing import Iterator, Optional, Sequence, overload

from .errors import AggregateError, GroupingError
from .expr import children, expr_key, find_aggregates, has_aggregate
from .parser import ColumnRef, Expr, FuncCall, Literal, OrderKey, Query, SelectItem, parse


class Stage:
    """Base class of plan stages; ``name`` identifies the stage kind."""

    name = "stage"


@dataclasses.dataclass(frozen=True)
class ScanStage(Stage):
    table: str
    name: str = "scan"


@dataclasses.dataclass(frozen=True)
class JoinStage(Stage):
    kind: str  # INNER or LEFT
    table: str
    on: Expr
    name: str = "join"


@dataclasses.dataclass(frozen=True)
class FilterStage(Stage):
    predicate: Expr
    name: str = "filter"


@dataclasses.dataclass(frozen=True)
class GroupStage(Stage):
    keys: tuple[Expr, ...]
    aggregates: tuple[FuncCall, ...]
    name: str = "group"


@dataclasses.dataclass(frozen=True)
class HavingStage(Stage):
    predicate: Expr
    name: str = "having"


@dataclasses.dataclass(frozen=True)
class ProjectStage(Stage):
    items: tuple[SelectItem, ...]
    name: str = "project"


@dataclasses.dataclass(frozen=True)
class DistinctStage(Stage):
    name: str = "distinct"


@dataclasses.dataclass(frozen=True)
class SortStage(Stage):
    keys: tuple[OrderKey, ...]
    name: str = "sort"


@dataclasses.dataclass(frozen=True)
class OffsetStage(Stage):
    count: int
    name: str = "offset"


@dataclasses.dataclass(frozen=True)
class LimitStage(Stage):
    count: int
    name: str = "limit"


class Plan(Sequence[Stage]):
    """An ordered, read-only sequence of stages."""

    def __init__(self, stages: Sequence[Stage]) -> None:
        self._stages = tuple(stages)

    @overload
    def __getitem__(self, index: int) -> Stage: ...

    @overload
    def __getitem__(self, index: slice) -> Sequence[Stage]: ...

    def __getitem__(self, index: int | slice) -> Stage | Sequence[Stage]:
        return self._stages[index]

    def __len__(self) -> int:
        return len(self._stages)

    def __iter__(self) -> Iterator[Stage]:
        return iter(self._stages)

    @property
    def stage_names(self) -> list[str]:
        return [s.name for s in self._stages]

    def find(self, name: str) -> Optional[Stage]:
        for s in self._stages:
            if s.name == name:
                return s
        return None

    def __repr__(self) -> str:
        return f"Plan({' -> '.join(self.stage_names)})"


# --- validation helpers -------------------------------------------------------


def check_grouped(node: Expr, group_keys: set[tuple], aliases: Optional[set[str]] = None) -> None:
    """Raise GroupingError unless ``node`` is built only from grouping expressions,
    aggregates, literals and (for ORDER BY) output aliases. This is slightly more
    permissive than the letter of section 8.2 rule 3: ``SELECT a + 1 ... GROUP BY a``
    is accepted, while a bare non-grouped column reference is rejected."""
    if expr_key(node) in group_keys:
        return
    if isinstance(node, Literal):
        return
    if isinstance(node, FuncCall) and node.is_aggregate:
        return
    if isinstance(node, ColumnRef):
        if aliases and node.table is None and node.name in aliases:
            return
        # ``t.c`` and ``c`` denote the same grouping column.
        for key in group_keys:
            if key[0] == "col" and key[2] == node.name and (
                key[1] is None or node.table is None or key[1] == node.table
            ):
                return
        label = f"{node.table}.{node.name}" if node.table else node.name
        raise GroupingError(f"column {label!r} is neither aggregated nor grouped")
    for child in children(node):
        check_grouped(child, group_keys, aliases)


def _no_aggregates(node: Optional[Expr], clause: str) -> None:
    if node is not None and has_aggregate(node):
        raise AggregateError(f"aggregates are not allowed in {clause}")


def _collect_aggregates(query: Query) -> tuple[FuncCall, ...]:
    found: list[FuncCall] = []
    for item in query.select:
        if item.expr is not None:
            find_aggregates(item.expr, found)
    if query.having is not None:
        find_aggregates(query.having, found)
    for key in query.order_by:
        find_aggregates(key.expr, found)
    unique: dict[tuple, FuncCall] = {}
    for agg in found:
        unique.setdefault(expr_key(agg), agg)
    return tuple(unique.values())


def _grouping_stages(query: Query, aggregates: tuple[FuncCall, ...]) -> list[Stage]:
    keys = {expr_key(g) for g in query.group_by}
    for item in query.select:
        if item.star:
            raise GroupingError("'*' cannot be used with grouping or aggregates")
        assert item.expr is not None
        check_grouped(item.expr, keys)
    stages: list[Stage] = [GroupStage(tuple(query.group_by), aggregates)]
    if query.having is not None:
        check_grouped(query.having, keys)
        stages.append(HavingStage(query.having))
    return stages


def plan(query: Query) -> Plan:
    stages: list[Stage] = [ScanStage(query.table)]
    if query.join is not None:
        _no_aggregates(query.join.on, "ON")
        stages.append(JoinStage(query.join.kind, query.join.table, query.join.on))
    if query.where is not None:
        _no_aggregates(query.where, "WHERE")
        stages.append(FilterStage(query.where))
    for g in query.group_by:
        _no_aggregates(g, "GROUP BY")
    aggregates = _collect_aggregates(query)
    # HAVING without GROUP BY treats the whole input as one group, like SQL.
    grouped = bool(query.group_by) or bool(aggregates) or query.having is not None
    if grouped:
        stages.extend(_grouping_stages(query, aggregates))
    stages.append(ProjectStage(tuple(query.select)))
    if query.distinct:
        stages.append(DistinctStage())
    if query.order_by:
        stages.append(SortStage(tuple(query.order_by)))
    if query.offset is not None:
        stages.append(OffsetStage(query.offset))
    if query.limit is not None:
        stages.append(LimitStage(query.limit))
    return Plan(stages)


def plan_sql(src: str) -> Plan:
    return plan(parse(src))
