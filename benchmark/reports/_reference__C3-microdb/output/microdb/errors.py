"""Exception hierarchy for microdb."""

from __future__ import annotations

__all__ = [
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


class MicroDBError(Exception):
    """Base class for every error raised by this package."""


class _PositionedError(MicroDBError):
    """Shared base for the two errors that carry a source offset."""

    def __init__(self, message: str, offset: int) -> None:
        self.offset = offset
        super().__init__(f"{message} at offset {offset}")


class LexError(_PositionedError):
    """The input could not be split into tokens."""


class ParseError(_PositionedError):
    """The token stream is not a valid query."""


class SchemaError(MicroDBError):
    """A table definition is inconsistent."""


class TypeMismatchError(MicroDBError):
    """An operation received a value of a type it cannot handle."""


class UnknownColumnError(MicroDBError):
    """A column reference does not resolve."""


class AmbiguousColumnError(MicroDBError):
    """An unqualified column reference matches more than one table."""


class UnknownTableError(MicroDBError):
    """A qualified reference names a table that is not in scope."""


class UnknownFunctionError(MicroDBError):
    """A call names a function that does not exist."""


class ArityError(MicroDBError):
    """A call passed the wrong number of arguments."""

    def __init__(self, name: str, expected: str, got: int) -> None:
        super().__init__(f"{name}() expects {expected} arguments, got {got}")


class AggregateError(MicroDBError):
    """An aggregate appeared somewhere it is not allowed."""


class GroupingError(MicroDBError):
    """A projection is not compatible with the GROUP BY clause."""
