"""In-memory relational query engine."""

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
from microdb.executor import Result, execute, execute_plan
from microdb.planner import Plan, plan
from microdb.schema import Column, Table
from microdb.value import (
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

__all__ = [
    "AggregateError",
    "AmbiguousColumnError",
    "ArityError",
    "Column",
    "GroupingError",
    "LexError",
    "MicroDBError",
    "ParseError",
    "Plan",
    "Result",
    "SchemaError",
    "Table",
    "TypeMismatchError",
    "UnknownColumnError",
    "UnknownFunctionError",
    "UnknownTableError",
    "and_",
    "arith",
    "compare_eq",
    "compare_lt",
    "execute",
    "execute_plan",
    "is_numeric",
    "negate",
    "not_",
    "or_",
    "plan",
    "type_of",
]
