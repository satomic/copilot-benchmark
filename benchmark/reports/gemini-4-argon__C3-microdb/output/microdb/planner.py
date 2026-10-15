from __future__ import annotations

from collections.abc import Iterator, Sequence
import dataclasses

from microdb.errors import AggregateError
from microdb.expr import validate_expr_functions
from microdb.parser import (
    AggregateCall,
    BinaryExpr,
    Expr,
    ExprSelectItem,
    FuncCall,
    IsNullExpr,
    JoinClause,
    OrderItem,
    Query,
    SelectItem,
    UnaryExpr,
    contains_aggregate,
)


@dataclasses.dataclass(frozen=True)
class Stage:
    name: str


@dataclasses.dataclass(frozen=True)
class FromJoinStage(Stage):
    from_table: str
    join: JoinClause | None


@dataclasses.dataclass(frozen=True)
class WhereStage(Stage):
    predicate: Expr


@dataclasses.dataclass(frozen=True)
class GroupStage(Stage):
    keys: tuple[Expr, ...]


@dataclasses.dataclass(frozen=True)
class AggregateStage(Stage):
    aggregates: tuple[AggregateCall, ...]


@dataclasses.dataclass(frozen=True)
class HavingStage(Stage):
    predicate: Expr


@dataclasses.dataclass(frozen=True)
class SelectStage(Stage):
    items: tuple[SelectItem, ...]


@dataclasses.dataclass(frozen=True)
class DistinctStage(Stage):
    pass


@dataclasses.dataclass(frozen=True)
class OrderStage(Stage):
    items: tuple[OrderItem, ...]


@dataclasses.dataclass(frozen=True)
class SliceStage(Stage):
    offset: int | None
    limit: int | None


class Plan(Sequence[Stage]):
    def __init__(
        self, query: Query, stages: Sequence[Stage], is_grouped: bool
    ) -> None:
        self.query: Query = query
        self.stages: tuple[Stage, ...] = tuple(stages)
        self.is_grouped: bool = is_grouped

    def __getitem__(self, index: int | slice) -> Stage | Sequence[Stage]:  # type: ignore[override]
        return self.stages[index]

    def __len__(self) -> int:
        return len(self.stages)

    def __iter__(self) -> Iterator[Stage]:
        return iter(self.stages)

    def __repr__(self) -> str:
        return f"Plan({list(self.stages)!r})"


def _collect_aggregates(expr: Expr, out: list[AggregateCall]) -> None:
    if isinstance(expr, AggregateCall):
        out.append(expr)
    elif isinstance(expr, UnaryExpr):
        _collect_aggregates(expr.operand, out)
    elif isinstance(expr, BinaryExpr):
        _collect_aggregates(expr.left, out)
        _collect_aggregates(expr.right, out)
    elif isinstance(expr, IsNullExpr):
        _collect_aggregates(expr.operand, out)
    elif isinstance(expr, FuncCall):
        for arg in expr.args:
            _collect_aggregates(arg, out)


def _validate_query(query: Query) -> list[AggregateCall]:
    if query.join is not None:
        if contains_aggregate(query.join.on):
            raise AggregateError("Aggregate functions are not allowed in JOIN ON")
        validate_expr_functions(query.join.on)
    if query.where is not None:
        if contains_aggregate(query.where):
            raise AggregateError("Aggregate functions are not allowed in WHERE")
        validate_expr_functions(query.where)
    for g in query.group_by:
        if contains_aggregate(g):
            raise AggregateError("Aggregate functions are not allowed in GROUP BY")
        validate_expr_functions(g)
    aggs: list[AggregateCall] = []
    if query.having is not None:
        validate_expr_functions(query.having)
        _collect_aggregates(query.having, aggs)
    for item in query.select_items:
        if isinstance(item, ExprSelectItem):
            validate_expr_functions(item.expr)
            _collect_aggregates(item.expr, aggs)
    for order_item in query.order_by:
        validate_expr_functions(order_item.expr)
        _collect_aggregates(order_item.expr, aggs)
    return aggs


def plan(query: Query) -> Plan:
    aggs = _validate_query(query)
    is_grouped = bool(query.group_by) or (query.having is not None) or bool(aggs)
    stages: list[Stage] = [
        FromJoinStage(name="FROM", from_table=query.from_table, join=query.join)
    ]
    if query.where is not None:
        stages.append(WhereStage(name="WHERE", predicate=query.where))
    if query.group_by:
        stages.append(GroupStage(name="GROUP_BY", keys=query.group_by))
    if is_grouped:
        stages.append(AggregateStage(name="AGGREGATE", aggregates=tuple(aggs)))
    if query.having is not None:
        stages.append(HavingStage(name="HAVING", predicate=query.having))
    stages.append(SelectStage(name="SELECT", items=query.select_items))
    if query.distinct:
        stages.append(DistinctStage(name="DISTINCT"))
    if query.order_by:
        stages.append(OrderStage(name="ORDER_BY", items=query.order_by))
    if query.offset is not None or query.limit is not None:
        stages.append(SliceStage(name="SLICE", offset=query.offset, limit=query.limit))
    return Plan(query=query, stages=stages, is_grouped=is_grouped)
