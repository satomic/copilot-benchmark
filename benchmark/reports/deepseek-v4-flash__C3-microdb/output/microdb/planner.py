"""Query planner: converts a Query into an ordered list of Plan stages."""

from dataclasses import dataclass, field
from typing import Any

from microdb.parser import Query


# ── Plan stages ────────────────────────────────────────────────────────


@dataclass
class ScanStage:
    """Read all rows from a table."""
    table: str


@dataclass
class JoinStage:
    """Perform a join with another table."""
    join_type: str  # "INNER" or "LEFT"
    table: str
    on: Any


@dataclass
class FilterStage:
    """Filter rows (WHERE or HAVING)."""
    predicate: Any


@dataclass
class GroupByStage:
    """Form groups."""
    keys: list[Any] = field(default_factory=list)


@dataclass
class SelectStage:
    """Project columns (SELECT)."""
    items: list[Any] = field(default_factory=list)


@dataclass
class DistinctStage:
    """Remove duplicate rows."""
    pass


@dataclass
class SortStage:
    """Sort rows."""
    keys: list[Any] = field(default_factory=list)  # list of (expr, ascending)


@dataclass
class OffsetStage:
    """Skip N rows."""
    n: int


@dataclass
class LimitStage:
    """Keep at most N rows."""
    n: int
    pass


Plan = list[Any]


def plan(query: Query) -> Plan:
    """Convert a Query into an ordered list of plan stages."""
    stages: Plan = []

    # 1. FROM
    stages.append(ScanStage(table=query.from_table))

    # 2. JOIN
    if query.join is not None:
        stages.append(
            JoinStage(
                join_type=query.join.type,
                table=query.join.table,
                on=query.join.on,
            )
        )

    # 3. WHERE
    if query.where is not None:
        stages.append(FilterStage(predicate=query.where))

    # 4. GROUP BY
    if query.group_by:
        stages.append(GroupByStage(keys=query.group_by))

    # 5. HAVING
    if query.having is not None:
        stages.append(FilterStage(predicate=query.having))

    # 6. SELECT
    stages.append(SelectStage(items=query.select_items))

    # 7. DISTINCT
    if query.distinct:
        stages.append(DistinctStage())

    # 8. ORDER BY
    if query.order_by:
        stages.append(
            SortStage(
                keys=[(ob.expr, ob.ascending) for ob in query.order_by]
            )
        )

    # 9. OFFSET
    if query.offset is not None:
        stages.append(OffsetStage(n=query.offset))

    # 10. LIMIT
    if query.limit is not None:
        stages.append(LimitStage(n=query.limit))

    return stages