import importlib

from .errors import *
from .executor import Result, execute, execute_plan
from .planner import Plan, plan
from .schema import Column, Table
from .parser import Query


def __getattr__(name: str) -> object:
    if name == "__main__":
        return importlib.import_module(f"{__name__}.__main__")
    raise AttributeError(name)


__all__ = [
    "Result",
    "Query",
    "Column",
    "Table",
    "Plan",
    "execute",
    "execute_plan",
    "plan",
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
