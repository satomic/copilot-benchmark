"""Exception hierarchy for the microvm package."""


class MicroVMError(Exception):
    """Base class for all microvm errors."""


class LexError(MicroVMError):
    """Raised by the lexer on malformed source text."""

    def __init__(self, message: str, offset: int) -> None:
        super().__init__(message)
        self.offset = offset


class ParseError(MicroVMError):
    """Raised by the parser on malformed token streams."""

    def __init__(self, message: str, offset: int) -> None:
        super().__init__(message)
        self.offset = offset


class CompileError(MicroVMError):
    """Raised by the compiler for static/semantic errors."""


class SerializationError(MicroVMError):
    """Raised by the serializer for malformed or invalid binary data."""


class VMRuntimeError(MicroVMError):
    """Raised by the virtual machine for runtime type/value errors."""


class StepLimitError(VMRuntimeError):
    """Raised when the VM exceeds its step budget."""
