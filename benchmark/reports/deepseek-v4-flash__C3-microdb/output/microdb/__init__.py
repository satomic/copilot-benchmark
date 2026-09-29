"""microdb: an in-memory relational query engine."""

from microdb.lexer import tokenize
from microdb.parser import parse
from microdb.planner import plan
from microdb.executor import execute_plan, Result
from microdb.schema import Column, Table
from microdb.errors import MicroDBError

__all__ = [
    "tokenize",
    "parse",
    "plan",
    "execute",
    "execute_plan",
    "Result",
    "Column",
    "Table",
    "MicroDBError",
]


def execute(query: str, tables: dict[str, Table]) -> Result:
    """Parse, plan, and execute a query against the given tables.

    This is the main public API entry point.
    """
    parsed = parse(query)
    pipeline = plan(parsed)
    return execute_plan(pipeline, tables)