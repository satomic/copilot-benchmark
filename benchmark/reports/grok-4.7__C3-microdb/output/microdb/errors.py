"""Exception hierarchy for microdb."""

from __future__ import annotations


class MicroDBError(Exception):
    """Base error for every microdb failure."""


class LexError(MicroDBError):
    """Lexical error at a zero-based character offset."""

    def __init__(self, message: str, offset: int) -> None:
        super().__init__(message)
        self.offset = offset


class ParseError(MicroDBError):
    """Syntax error at a zero-based character offset."""

    def __init__(self, message: str, offset: int) -> None:
        super().__init__(message)
        self.offset = offset


class SchemaError(MicroDBError):
    """Invalid table schema or row shape."""


class TypeMismatchError(MicroDBError):
    """Operand types are not valid for the operator or function."""


class UnknownColumnError(MicroDBError):
    """A column reference does not exist."""


class AmbiguousColumnError(MicroDBError):
    """A column reference matches more than one column."""


class UnknownTableError(MicroDBError):
    """A table name is not in scope."""


class UnknownFunctionError(MicroDBError):
    """A function name is not defined."""

    def __init__(self, name: str) -> None:
        self.name = name
        super().__init__(f"unknown function {name}")


class ArityError(MicroDBError):
    """A function was called with the wrong number of arguments."""

    def __init__(self, name: str, expected: int, actual: int, at_least: bool = False) -> None:
        self.name = name
        self.expected = expected
        self.actual = actual
        if at_least:
            message = f"{name} expects at least {expected} arguments, got {actual}"
        else:
            message = f"{name} expects {expected} arguments, got {actual}"
        super().__init__(message)


class AggregateError(MicroDBError):
    """An aggregate was used where it is not allowed."""


class GroupingError(MicroDBError):
    """A select item or having clause violates grouping rules."""
