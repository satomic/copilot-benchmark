"""Exception hierarchy for microdb."""

from __future__ import annotations


class MicroDBError(Exception):
    """Base exception for all microdb errors."""


class LexError(MicroDBError):
    """Lexer error with a zero-based character offset."""

    def __init__(self, message: str, offset: int) -> None:
        super().__init__(f"{message} at offset {offset}")
        self.offset: int = offset


class ParseError(MicroDBError):
    """Parser error with a zero-based character offset."""

    def __init__(self, message: str, offset: int) -> None:
        super().__init__(f"{message} at offset {offset}")
        self.offset: int = offset


class SchemaError(MicroDBError):
    """Schema definition or validation error."""


class TypeMismatchError(MicroDBError):
    """Operand or argument type mismatch error."""


class UnknownColumnError(MicroDBError):
    """Referenced column does not exist."""


class AmbiguousColumnError(MicroDBError):
    """Unqualified column exists in multiple tables."""


class UnknownTableError(MicroDBError):
    """Referenced table does not exist."""


class UnknownFunctionError(MicroDBError):
    """Referenced function does not exist."""


class ArityError(MicroDBError):
    """Function called with incorrect number of arguments."""


class AggregateError(MicroDBError):
    """Illegal aggregate usage (e.g., in WHERE)."""


class GroupingError(MicroDBError):
    """Illegal select item or expression under GROUP BY."""
