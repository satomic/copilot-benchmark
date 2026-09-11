from .parser import Query, Expr
from .expr import is_aggregate_expr
import dataclasses


@dataclasses.dataclass
class Stage:
    name: str


@dataclasses.dataclass
class FromStage(Stage):
    table: str
    join_type: str | None = None
    join_table: str | None = None
    join_on_expr: Expr | None = None


@dataclasses.dataclass
class WhereStage(Stage):
    expr: Expr


@dataclasses.dataclass
class GroupByStage(Stage):
    exprs: list[Expr]


@dataclasses.dataclass
class HavingStage(Stage):
    expr: Expr


@dataclasses.dataclass
class SelectStage(Stage):
    distinct: bool
    items: list[tuple[Expr | None, str | None, str | None]]


@dataclasses.dataclass
class OrderByStage(Stage):
    items: list[tuple[Expr, str]]


@dataclasses.dataclass
class LimitOffsetStage(Stage):
    limit: int | None
    offset: int | None


Plan = list[Stage]


def plan(query: Query) -> Plan:
    """Create an execution plan from a query."""
    stages: Plan = []
    
    stages.append(FromStage(
        name="FROM",
        table=query.from_table or "",
        join_type=query.join.type if query.join else None,
        join_table=query.join.table if query.join else None,
        join_on_expr=query.join.on_expr if query.join else None
    ))
    
    if query.where_expr:
        stages.append(WhereStage(name="WHERE", expr=query.where_expr))
    
    if query.group_by:
        stages.append(GroupByStage(name="GROUP_BY", exprs=query.group_by))
    
    has_aggregate = any(
        is_aggregate_expr(item.expr)
        for item in query.select_items
        if item.expr
    ) or (query.having_expr and is_aggregate_expr(query.having_expr))
    
    if has_aggregate and not query.group_by:
        stages.append(GroupByStage(name="GROUP_BY", exprs=[]))
    
    if query.having_expr:
        stages.append(HavingStage(name="HAVING", expr=query.having_expr))
    
    select_items = []
    for item in query.select_items:
        select_items.append((item.expr, item.alias, item.star_table))
    
    stages.append(SelectStage(
        name="SELECT",
        distinct=query.distinct,
        items=select_items
    ))
    
    if query.distinct:
        stages.append(Stage(name="DISTINCT"))
    
    if query.order_by:
        stages.append(OrderByStage(name="ORDER_BY", items=query.order_by))
    
    if query.limit is not None or query.offset is not None:
        stages.append(LimitOffsetStage(
            name="LIMIT_OFFSET",
            limit=query.limit,
            offset=query.offset
        ))
    
    return stages
