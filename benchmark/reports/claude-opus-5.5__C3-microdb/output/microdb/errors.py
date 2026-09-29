"""Exception hierarchy for microdb."""

from __future__ import annotations


class MicroDBError(Exception):
    """Base class of every error raised by microdb."""


class LexError(MicroDBError):
    """Raised when the query text cannot be tokenized."""

    def __init__(self, message: str, offset: int) -> None:
        super().__init__(f"{message} at offset {offset}")
        self.offset = offset


class ParseError(MicroDBError):
    """Raised when the token stream does not match the grammar."""

    def __init__(self, message: str, offset: int) -> None:
        super().__init__(f"{message} at offset {offset}")
        self.offset = offset


class SchemaError(MicroDBError):
    """Raised for invalid table definitions or data."""


class TypeMismatchError(MicroDBError):
    """Raised when operand types are incompatible."""


class UnknownColumnError(MicroDBError):
    """Raised when a column reference cannot be resolved."""


class AmbiguousColumnError(MicroDBError):
    """Raised when a column reference matches more than one column."""


class UnknownTableError(MicroDBError):
    """Raised when a table name cannot be resolved."""


class UnknownFunctionError(MicroDBError):
    """Raised when a function name is not known."""


class ArityError(MicroDBError):
    """Raised when a function is called with the wrong number of arguments."""


class AggregateError(MicroDBError):
    """Raised when an aggregate is used where it is not allowed."""


class GroupingError(MicroDBError):
    """Raised when a projected expression is neither grouped nor aggregated."""
