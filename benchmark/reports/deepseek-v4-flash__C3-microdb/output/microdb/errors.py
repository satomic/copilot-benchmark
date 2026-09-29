"""Exception hierarchy for microdb."""


class MicroDBError(Exception):
    """Base exception for all microdb errors."""


class LexError(MicroDBError):
    """Lexer error with zero-based character offset."""

    def __init__(self, message: str, offset: int) -> None:
        super().__init__(message)
        self.offset = offset


class ParseError(MicroDBError):
    """Parser error with zero-based character offset."""

    def __init__(self, message: str, offset: int) -> None:
        super().__init__(message)
        self.offset = offset


class SchemaError(MicroDBError):
    """Schema validation error."""


class TypeMismatchError(MicroDBError):
    """Type mismatch in operation."""


class UnknownColumnError(MicroDBError):
    """Reference to unknown column."""


class AmbiguousColumnError(MicroDBError):
    """Unqualified column reference that matches multiple tables."""


class UnknownTableError(MicroDBError):
    """Reference to unknown table."""


class UnknownFunctionError(MicroDBError):
    """Reference to unknown function."""


class ArityError(MicroDBError):
    """Wrong number of arguments to a function."""


class AggregateError(MicroDBError):
    """Aggregate used in wrong context."""


class GroupingError(MicroDBError):
    """Invalid SELECT item with GROUP BY."""