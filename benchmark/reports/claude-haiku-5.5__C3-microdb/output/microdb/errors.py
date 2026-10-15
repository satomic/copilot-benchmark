"""Exception hierarchy for microdb."""


class MicroDBError(Exception):
    """Base class for every error raised by microdb."""


class LexError(MicroDBError):
    """Invalid character or unterminated literal; ``offset`` is zero-based."""

    def __init__(self, message: str, offset: int) -> None:
        super().__init__(message)
        self.offset = offset


class ParseError(MicroDBError):
    """Query does not match the grammar; ``offset`` is zero-based."""

    def __init__(self, message: str, offset: int) -> None:
        super().__init__(message)
        self.offset = offset


class SchemaError(MicroDBError):
    """Invalid table definition or cell value."""


class TypeMismatchError(MicroDBError):
    """Operands or arguments have an incompatible type."""


class UnknownColumnError(MicroDBError):
    """Column reference does not resolve."""


class AmbiguousColumnError(MicroDBError):
    """Unqualified column name exists in more than one table."""


class UnknownTableError(MicroDBError):
    """Table name is not supplied or not in scope."""


class UnknownFunctionError(MicroDBError):
    """Function name is not known."""


class ArityError(MicroDBError):
    """Function called with the wrong number of arguments."""


class AggregateError(MicroDBError):
    """Aggregate used where it is not allowed."""


class GroupingError(MicroDBError):
    """Select item is neither grouped nor aggregated."""
