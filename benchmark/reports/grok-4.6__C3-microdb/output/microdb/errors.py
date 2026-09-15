"""Exception hierarchy for microdb."""


class MicroDBError(Exception):
    """Base error for all microdb failures."""


class LexError(MicroDBError):
    def __init__(self, message: str, offset: int) -> None:
        super().__init__(message)
        self.offset = offset


class ParseError(MicroDBError):
    def __init__(self, message: str, offset: int) -> None:
        super().__init__(message)
        self.offset = offset


class SchemaError(MicroDBError):
    """Invalid table schema or row payload."""


class TypeMismatchError(MicroDBError):
    """Value has the wrong type for an operation."""


class UnknownColumnError(MicroDBError):
    """Column name could not be resolved."""


class AmbiguousColumnError(MicroDBError):
    """Column name matches more than one column."""


class UnknownTableError(MicroDBError):
    """Table name is not in scope."""


class UnknownFunctionError(MicroDBError):
    """Scalar or aggregate function does not exist."""


class ArityError(MicroDBError):
    def __init__(self, name: str, expected: int, got: int) -> None:
        super().__init__(f"{name} expected {expected} argument(s), got {got}")
        self.name = name
        self.expected = expected
        self.got = got


class AggregateError(MicroDBError):
    """Aggregate used in a context that forbids it."""


class GroupingError(MicroDBError):
    """SELECT item is illegal under GROUP BY rules."""
