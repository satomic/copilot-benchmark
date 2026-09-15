"""Exception hierarchy for microvm."""


class MicroVMError(Exception):
    """Base exception for all microvm errors."""


class LexError(MicroVMError):
    """Lexer error with a zero-based character offset."""

    def __init__(self, message: str, offset: int) -> None:
        super().__init__(message)
        self.offset: int = offset


class ParseError(MicroVMError):
    """Parser error with a zero-based character offset."""

    def __init__(self, message: str, offset: int) -> None:
        super().__init__(message)
        self.offset: int = offset


class CompileError(MicroVMError):
    """Compiler error."""


class SerializationError(MicroVMError):
    """Binary format serialization or deserialization error."""


class VMRuntimeError(MicroVMError):
    """Runtime execution error."""


class StepLimitError(VMRuntimeError):
    """Execution exceeded the step limit."""
