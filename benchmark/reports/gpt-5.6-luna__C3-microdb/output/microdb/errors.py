class MicroDBError(Exception):
    """Base exception."""


class LexError(MicroDBError):
    def __init__(self, message: str, offset: int) -> None:
        super().__init__(message)
        self.offset = offset


class ParseError(MicroDBError):
    def __init__(self, message: str, offset: int) -> None:
        super().__init__(message)
        self.offset = offset


class SchemaError(MicroDBError):
    pass


class TypeMismatchError(MicroDBError):
    pass


class UnknownColumnError(MicroDBError):
    pass


class AmbiguousColumnError(MicroDBError):
    pass


class UnknownTableError(MicroDBError):
    pass


class UnknownFunctionError(MicroDBError):
    pass


class ArityError(MicroDBError):
    pass


class AggregateError(MicroDBError):
    pass


class GroupingError(MicroDBError):
    pass
