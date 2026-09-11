"""Exception hierarchy for microdb."""

from __future__ import annotations


class MicroDBError(Exception):
    """Base class for all microdb errors."""


class LexError(MicroDBError):
    """Raised when the lexer encounters an invalid character."""

    def __init__(self, message: str, offset: int) -> None:
        super().__init__(message)
        self.offset = offset


class ParseError(MicroDBError):
    """Raised when the parser encounters invalid syntax."""

    def __init__(self, message: str, offset: int) -> None:
        super().__init__(message)
        self.offset = offset


class SchemaError(MicroDBError):
    """Raised when a Table's schema or data is invalid."""


class TypeMismatchError(MicroDBError):
    """Raised when an operation is applied to incompatible types."""


class UnknownColumnError(MicroDBError):
    """Raised when a referenced column does not exist."""


class AmbiguousColumnError(MicroDBError):
    """Raised when an unqualified column name matches more than one table."""


class UnknownTableError(MicroDBError):
    """Raised when a table qualifier does not refer to a known table."""


class UnknownFunctionError(MicroDBError):
    """Raised when a function name is not recognized."""


class ArityError(MicroDBError):
    """Raised when a function call has the wrong number of arguments."""


class AggregateError(MicroDBError):
    """Raised when an aggregate is used in a disallowed position."""


class GroupingError(MicroDBError):
    """Raised when a SELECT item is not an aggregate or grouping expression."""
