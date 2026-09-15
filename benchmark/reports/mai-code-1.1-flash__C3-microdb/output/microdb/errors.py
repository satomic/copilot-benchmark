class MicroDBError(Exception):
    pass


class LexError(MicroDBError):
    def __init__(self, offset: int) -> None:
        super().__init__(f"LexError at offset {offset}")
        self.offset = offset


class ParseError(MicroDBError):
    def __init__(self, offset: int) -> None:
        super().__init__(f"ParseError at offset {offset}")
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
