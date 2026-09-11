"""microdb: a small in-memory relational query engine with SQL-style NULL semantics."""

from __future__ import annotations

from .aggregate import AGGREGATE_NAMES, Aggregator, make_aggregator
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
from .expr import Context, Scope, evaluate
from .lexer import Token, tokenize
from .parser import Expr, Query, parse
from .planner import Plan, Stage, plan
from .schema import Column, Table
from .value import (
    and_,
    arith,
    compare_eq,
    compare_lt,
    concat,
    is_numeric,
    negate,
    not_,
    or_,
    type_of,
)

__all__ = [
    "AGGREGATE_NAMES",
    "AggregateError",
    "Aggregator",
    "AmbiguousColumnError",
    "ArityError",
    "Column",
    "Context",
    "Expr",
    "GroupingError",
    "LexError",
    "MicroDBError",
    "ParseError",
    "Plan",
    "Query",
    "Result",
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
    "compare_eq",
    "compare_lt",
    "concat",
    "evaluate",
    "execute",
    "execute_plan",
    "is_numeric",
    "make_aggregator",
    "negate",
    "not_",
    "or_",
    "parse",
    "plan",
    "tokenize",
    "type_of",
]
