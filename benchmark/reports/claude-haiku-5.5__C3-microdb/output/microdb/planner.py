"""Planner: turns a Query into an ordered Plan of named stages."""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar, Iterator

from .aggregate import AGGREGATE_NAMES
from .errors import AggregateError, GroupingError
from .expr import check_call, children, iter_nodes
from .parser import Call, Col, Expr, Join, OrderItem, Query, SelectItem, Star


@dataclass(frozen=True)
class ScanStage:
    name: ClassVar[str] = "scan"
    table: str
    join: Join | None


@dataclass(frozen=True)
class FilterStage:
    name: ClassVar[str] = "filter"
    predicate: Expr


@dataclass(frozen=True)
class GroupStage:
    name: ClassVar[str] = "group"
    keys: tuple


@dataclass(frozen=True)
class AggregateStage:
    name: ClassVar[str] = "aggregate"
    calls: tuple


@dataclass(frozen=True)
class HavingStage:
    name: ClassVar[str] = "having"
    predicate: Expr


@dataclass(frozen=True)
class ProjectStage:
    name: ClassVar[str] = "project"
    items: tuple


@dataclass(frozen=True)
class DistinctStage:
    name: ClassVar[str] = "distinct"


@dataclass(frozen=True)
class SortStage:
    name: ClassVar[str] = "sort"
    keys: tuple[OrderItem, ...]


@dataclass(frozen=True)
class SliceStage:
    name: ClassVar[str] = "slice"
    offset: int | None
    limit: int | None


class Plan:
    """An inspectable, ordered sequence of stages. Building it does not execute anything."""

    def __init__(self, stages: tuple) -> None:
        self._stages = tuple(stages)

    def __iter__(self) -> Iterator[object]:
        return iter(self._stages)

    def __len__(self) -> int:
        return len(self._stages)

    def __getitem__(self, index: int) -> object:
        return self._stages[index]

    @property
    def names(self) -> list[str]:
        return [stage.name for stage in self._stages]  # type: ignore[attr-defined]


def plan(query: Query) -> Plan:
    """Validate the query and build its stage pipeline."""
    _validate(query)
    aggs = _collect_aggregates(query)
    grouped = bool(query.group) or bool(aggs)
    stages: list[object] = [ScanStage(query.table, query.join)]
    if query.where is not None:
        stages.append(FilterStage(query.where))
    if grouped:
        _check_grouping(query)
        stages.append(GroupStage(query.group))
        stages.append(AggregateStage(aggs))
    if query.having is not None:
        stages.append(HavingStage(query.having))
    stages.append(ProjectStage(query.items))
    if query.distinct:
        stages.append(DistinctStage())
    if query.order:
        stages.append(SortStage(query.order))
    if query.limit is not None or query.offset is not None:
        stages.append(SliceStage(query.offset, query.limit))
    return Plan(tuple(stages))


def _all_exprs(query: Query) -> list[Expr]:
    exprs: list[Expr] = [item.expr for item in query.items if isinstance(item, SelectItem)]
    exprs += list(query.group)
    exprs += [o.expr for o in query.order]
    for extra in (query.where, query.having, query.join.on if query.join else None):
        if extra is not None:
            exprs.append(extra)
    return exprs


def _validate(query: Query) -> None:
    for expr in _all_exprs(query):
        for node in iter_nodes(expr):
            if isinstance(node, Call):
                check_call(node)
    for label, expr in _aggregate_free_exprs(query):
        if any(isinstance(n, Call) and n.name in AGGREGATE_NAMES for n in iter_nodes(expr)):
            raise AggregateError(f"aggregates are not allowed in {label}")


def _aggregate_free_exprs(query: Query) -> list[tuple[str, Expr]]:
    """Clauses in which aggregates are forbidden, with their names for messages."""
    result: list[tuple[str, Expr]] = []
    if query.where is not None:
        result.append(("WHERE", query.where))
    if query.join is not None:
        result.append(("JOIN ON", query.join.on))
    result += [("GROUP BY", key) for key in query.group]
    return result


def _collect_aggregates(query: Query) -> tuple:
    """Distinct aggregate calls from SELECT, HAVING and ORDER BY, in first-seen order."""
    roots: list[Expr] = [item.expr for item in query.items if isinstance(item, SelectItem)]
    roots += [query.having] if query.having is not None else []
    roots += [o.expr for o in query.order]
    seen: dict[Call, None] = {}
    for root in roots:
        for node in iter_nodes(root):
            if isinstance(node, Call) and node.name in AGGREGATE_NAMES:
                seen.setdefault(node, None)
    return tuple(seen)


def _check_grouping(query: Query) -> None:
    aliases = _output_names(query)
    for item in query.items:
        if isinstance(item, Star):
            raise GroupingError("'*' cannot be used with GROUP BY or aggregates")
        _check_group_expr(item.expr, query.group, frozenset())
    if query.having is not None:
        _check_group_expr(query.having, query.group, frozenset())
    for order in query.order:
        _check_group_expr(order.expr, query.group, aliases)


def _output_names(query: Query) -> frozenset[str]:
    names = set()
    for item in query.items:
        if isinstance(item, SelectItem):
            if item.alias is not None:
                names.add(item.alias)
            elif isinstance(item.expr, Col):
                names.add(item.expr.name)
            else:
                names.add(item.text)
    return frozenset(names)


def _check_group_expr(node: Expr, keys: tuple, aliases: frozenset[str]) -> None:
    """Every column must be a grouping key, an alias (ORDER BY only) or inside an aggregate."""
    if node in keys:
        return
    if isinstance(node, Call) and node.name in AGGREGATE_NAMES:
        return
    if isinstance(node, Col):
        if node.qualifier is None and node.name in aliases:
            return
        raise GroupingError(f"column {node.name!r} must appear in GROUP BY or inside an aggregate")
    for child in children(node):
        _check_group_expr(child, keys, aliases)
