"""microdb: an in-memory relational query engine."""

from __future__ import annotations

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
from .executor import Result, execute, execute_plan
from .lexer import Token, tokenize
from .parser import Query, parse
from .planner import Plan, plan
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
    "Query",
    "Result",
    "SchemaError",
    "Table",
    "Token",
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
    "parse",
    "plan",
    "tokenize",
    "type_of",
]
