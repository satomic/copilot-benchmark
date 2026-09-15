"""microdb: a small in-memory relational query engine."""

from __future__ import annotations

from .aggregate import AGGREGATE_NAMES, compute, contains_aggregate, find_aggregates
from .errors import (
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
from .executor import Result, execute_plan
from .expr import Row, Scope, call_scalar, eval_expr
from .lexer import Token, tokenize
from .parser import Query, parse
from .planner import Plan, Stage, plan
from .schema import Column, Table
from .value import (
    and_,
    arith,
    compare_eq,
    compare_lt,
    is_numeric,
    negate,
    not_,
    or_,
    type_of,
)


def execute(query: str, tables: dict[str, Table]) -> Result:
    """Parse, plan and execute a query string against in-memory tables."""
    return execute_plan(plan(parse(query)), tables)


__all__ = [
    "AGGREGATE_NAMES",
    "AggregateError",
    "AmbiguousColumnError",
    "ArityError",
    "Column",
    "GroupingError",
    "LexError",
    "MicroDBError",
    "ParseError",
    "Plan",
    "Query",
    "Result",
    "Row",
    "SchemaError",
    "Scope",
    "Stage",
    "Table",
    "Token",
    "TypeMismatchError",
    "UnknownColumnError",
    "UnknownFunctionError",
    "UnknownTableError",
    "and_",
    "arith",
    "call_scalar",
    "compare_eq",
    "compare_lt",
    "compute",
    "contains_aggregate",
    "eval_expr",
    "execute",
    "execute_plan",
    "find_aggregates",
    "is_numeric",
    "negate",
    "not_",
    "or_",
    "parse",
    "plan",
    "tokenize",
    "type_of",
]
