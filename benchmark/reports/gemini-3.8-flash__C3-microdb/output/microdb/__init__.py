"""microdb - In-memory relational query engine."""

from __future__ import annotations

from microdb.aggregate import evaluate_aggregate
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
from microdb.expr import (
    AggregateCall,
    BinaryOp,
    ColumnRef,
    CompareOp,
    EvalContext,
    Expr,
    FunctionCall,
    IsNullOp,
    Literal,
    LogicalOp,
    NotOp,
    UnaryOp,
    eval_expr,
)
from microdb.lexer import Token, lex
from microdb.parser import JoinClause, OrderItem, Query, SelectItem, parse
from microdb.planner import (
    AggregateStage,
    DistinctStage,
    FromStage,
    GroupByStage,
    HavingStage,
    JoinStage,
    OrderByStage,
    Plan,
    SelectStage,
    SliceStage,
    Stage,
    WhereStage,
    plan,
)
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


def execute(query: str, tables: dict[str, Table]) -> Result:
    """Parse, plan, and execute a query string against tables."""
    parsed_query = parse(query)
    planned = plan(parsed_query)
    return execute_plan(planned, tables)


__all__ = [
    "AggregateCall",
    "AggregateError",
    "AggregateStage",
    "AmbiguousColumnError",
    "ArityError",
    "BinaryOp",
    "Column",
    "ColumnRef",
    "CompareOp",
    "DistinctStage",
    "EvalContext",
    "Expr",
    "FromStage",
    "FunctionCall",
    "GroupByStage",
    "GroupingError",
    "HavingStage",
    "IsNullOp",
    "JoinClause",
    "JoinStage",
    "LexError",
    "Literal",
    "LogicalOp",
    "MicroDBError",
    "NotOp",
    "OrderByStage",
    "OrderItem",
    "ParseError",
    "Plan",
    "Query",
    "Result",
    "SchemaError",
    "SelectItem",
    "SelectStage",
    "SliceStage",
    "Stage",
    "Table",
    "Token",
    "TypeMismatchError",
    "UnaryOp",
    "UnknownColumnError",
    "UnknownFunctionError",
    "UnknownTableError",
    "WhereStage",
    "and_",
    "arith",
    "compare_eq",
    "compare_lt",
    "evaluate_aggregate",
    "eval_expr",
    "execute",
    "execute_plan",
    "is_numeric",
    "lex",
    "negate",
    "not_",
    "or_",
    "parse",
    "plan",
    "type_of",
]
