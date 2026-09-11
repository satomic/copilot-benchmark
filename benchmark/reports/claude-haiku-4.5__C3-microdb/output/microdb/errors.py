class MicroDBError(Exception):
    """Base exception for all microdb errors."""
    pass


class LexError(MicroDBError):
    """Lexical analysis error."""
    def __init__(self, message: str, offset: int) -> None:
        super().__init__(message)
        self.offset = offset


class ParseError(MicroDBError):
    """Parse error."""
    def __init__(self, message: str, offset: int) -> None:
        super().__init__(message)
        self.offset = offset


class SchemaError(MicroDBError):
    """Schema validation error."""
    pass


class TypeMismatchError(MicroDBError):
    """Type mismatch in operation."""
    pass


class UnknownColumnError(MicroDBError):
    """Column not found."""
    pass


class AmbiguousColumnError(MicroDBError):
    """Column reference is ambiguous."""
    pass


class UnknownTableError(MicroDBError):
    """Table not found."""
    pass


class UnknownFunctionError(MicroDBError):
    """Function not found."""
    pass


class ArityError(MicroDBError):
    """Function arity mismatch."""
    pass


class AggregateError(MicroDBError):
    """Aggregate function error."""
    pass


class GroupingError(MicroDBError):
    """Grouping error."""
    pass
