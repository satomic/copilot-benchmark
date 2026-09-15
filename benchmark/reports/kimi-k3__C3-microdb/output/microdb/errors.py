"""Exception hierarchy for microdb."""

from __future__ import annotations


class MicroDBError(Exception):
    """Base class for all microdb errors."""


class LexError(MicroDBError):
    """Raised when the lexer encounters an invalid character or token."""

    def __init__(self, message: str, offset: int) -> None:
        super().__init__(message)
        self.offset: int = offset


class ParseError(MicroDBError):
    """Raised when the parser encounters invalid syntax."""

    def __init__(self, message: str, offset: int) -> None:
        super().__init__(message)
        self.offset: int = offset


class SchemaError(MicroDBError):
    """Raised when a table definition or its rows are invalid."""


class TypeMismatchError(MicroDBError):
    """Raised when an operation receives a value of an incompatible type."""


class UnknownColumnError(MicroDBError):
    """Raised when a column reference cannot be resolved."""


class AmbiguousColumnError(MicroDBError):
    """Raised when an unqualified column name matches more than one table."""


class UnknownTableError(MicroDBError):
    """Raised when a qualified reference names an unknown table."""


class UnknownFunctionError(MicroDBError):
    """Raised when a scalar function name is not recognized."""


class ArityError(MicroDBError):
    """Raised when a function is called with the wrong number of arguments."""


class AggregateError(MicroDBError):
    """Raised when an aggregate function is used illegally."""


class GroupingError(MicroDBError):
    """Raised when a SELECT item violates GROUP BY rules."""
