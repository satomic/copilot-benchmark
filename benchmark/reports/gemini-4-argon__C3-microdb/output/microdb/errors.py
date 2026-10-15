from __future__ import annotations


class MicroDBError(Exception):
    """Base exception for all microdb errors."""


class LexError(MicroDBError):
    """Raised when lexical analysis encounters an invalid character or token."""

    def __init__(self, message: str = "Lexical error", offset: int = 0) -> None:
        super().__init__(message)
        self.offset: int = offset


class ParseError(MicroDBError):
    """Raised when parsing encounters invalid syntax."""

    def __init__(self, message: str = "Parse error", offset: int = 0) -> None:
        super().__init__(message)
        self.offset: int = offset


class SchemaError(MicroDBError):
    """Raised when a table schema or row data is invalid."""


class TypeMismatchError(MicroDBError):
    """Raised when an operation is applied to incompatible types."""


class UnknownColumnError(MicroDBError):
    """Raised when a referenced column does not exist."""


class AmbiguousColumnError(MicroDBError):
    """Raised when an unqualified column name matches multiple tables."""


class UnknownTableError(MicroDBError):
    """Raised when a referenced table does not exist."""


class UnknownFunctionError(MicroDBError):
    """Raised when a referenced function does not exist."""


class ArityError(MicroDBError):
    """Raised when a function is called with the wrong number of arguments."""


class AggregateError(MicroDBError):
    """Raised when an aggregate function is misused."""


class GroupingError(MicroDBError):
    """Raised when a non-grouped, non-aggregated expression is selected with GROUP BY."""
