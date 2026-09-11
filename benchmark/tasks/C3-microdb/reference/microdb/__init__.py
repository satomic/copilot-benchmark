"""microdb: an in-memory relational query engine with three-valued logic."""

from __future__ import annotations

from .aggregate import aggregate
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
from .expr import Scope, evaluate
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

__all__ = [
    "execute",
    "execute_plan",
    "Result",
    "plan",
    "Plan",
    "Stage",
    "parse",
    "Query",
    "tokenize",
    "Token",
    "Column",
    "Table",
    "Scope",
    "evaluate",
    "aggregate",
    "type_of",
    "is_numeric",
    "and_",
    "or_",
    "not_",
    "compare_eq",
    "compare_lt",
    "arith",
    "negate",
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
]
