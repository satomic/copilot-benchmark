"""microdb: an in-memory relational query engine (public surface)."""

from __future__ import annotations

from microdb.errors import (
    AggregateError,
    AmbiguousColumnError,
    ArityError,
    GroupingError,
    LexError,
    MicroDBError,
    ParseError,
    SchemaError,
    TypeMismatchError,
    UnknownColumnError,
    UnknownFunctionError,
    UnknownTableError,
)
from microdb.executor import Result, execute_plan
from microdb.parser import Query, parse
from microdb.planner import Plan, plan
from microdb.schema import Column, Table

__all__ = [
    "MicroDBError",
    "LexError",
    "ParseError",
    "SchemaError",
    "TypeMismatchError",
    "UnknownColumnError",
    "AmbiguousColumnError",
    "UnknownTableError",
    "UnknownFunctionError",
    "ArityError",
    "AggregateError",
    "GroupingError",
    "Column",
    "Table",
    "Query",
    "Plan",
    "Result",
    "parse",
    "plan",
    "execute_plan",
    "execute",
]


def execute(query: str, tables: dict) -> Result:
    """Parse, plan and execute query against tables, returning a Result."""
    parsed = parse(query)
    the_plan = plan(parsed)
    return execute_plan(the_plan, tables)
