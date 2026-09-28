class MicroVMError(Exception):
    """Base error for every microvm failure."""


class LexError(MicroVMError):
    """Lexical error. offset is a zero-based character index."""

    def __init__(self, message: str, offset: int) -> None:
        super().__init__(f"{message} at offset {offset}")
        self.offset = offset


class ParseError(MicroVMError):
    """Syntax error. offset is a zero-based character index."""

    def __init__(self, message: str, offset: int) -> None:
        super().__init__(f"{message} at offset {offset}")
        self.offset = offset


class CompileError(MicroVMError):
    """Compile-time semantic error."""


class SerializationError(MicroVMError):
    """Binary codec error."""


class VMRuntimeError(MicroVMError):
    """Error raised while executing bytecode."""


class StepLimitError(VMRuntimeError):
    """Raised when execution would exceed the instruction budget."""
