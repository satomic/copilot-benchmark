"""Public API of the in-memory relational engine."""

from .errors import (
    MicroDBError, LexError, ParseError, SchemaError, TypeMismatchError,
    UnknownColumnError, AmbiguousColumnError, UnknownTableError,
    UnknownFunctionError, ArityError, AggregateError, GroupingError,
)
from .executor import Result, execute, execute_plan
from .lexer import Token, tokenize
from .parser import Query, parse
from .planner import Plan, Stage, plan
from .schema import Column, Table
from .value import type_of, is_numeric, and_, or_, not_, compare_eq, compare_lt, arith, negate


__all__ = [
    "Column", "Table", "Result", "execute", "execute_plan", "Token", "tokenize",
    "Query", "parse", "Plan", "Stage", "plan", "type_of", "is_numeric", "and_",
    "or_", "not_", "compare_eq", "compare_lt", "arith", "negate", "MicroDBError",
    "LexError", "ParseError", "SchemaError", "TypeMismatchError", "UnknownColumnError",
    "AmbiguousColumnError", "UnknownTableError", "UnknownFunctionError", "ArityError",
    "AggregateError", "GroupingError",
]
