"""Exception hierarchy for microdb."""

from __future__ import annotations


class MicroDBError(Exception):
    """Base class for every error raised by microdb."""


class LexError(MicroDBError):
    """Raised when the lexer meets a character it cannot tokenize."""

    def __init__(self, message: str, offset: int) -> None:
        super().__init__(message)
        self.offset: int = offset


class ParseError(MicroDBError):
    """Raised when the token stream does not match the grammar."""

    def __init__(self, message: str, offset: int) -> None:
        super().__init__(message)
        self.offset: int = offset


class SchemaError(MicroDBError):
    """Raised for invalid table definitions or unknown column lookups."""


class TypeMismatchError(MicroDBError):
    """Raised when operand types are not compatible with an operation."""


class UnknownColumnError(MicroDBError):
    """Raised when a column reference cannot be resolved."""


class AmbiguousColumnError(MicroDBError):
    """Raised when an unqualified column exists in more than one table."""


class UnknownTableError(MicroDBError):
    """Raised when a table name is not known."""


class UnknownFunctionError(MicroDBError):
    """Raised when a function name is not known."""


class ArityError(MicroDBError):
    """Raised when a function is called with the wrong number of arguments."""


class AggregateError(MicroDBError):
    """Raised when an aggregate is used where it is not allowed."""


class GroupingError(MicroDBError):
    """Raised when a projection is not compatible with GROUP BY."""
