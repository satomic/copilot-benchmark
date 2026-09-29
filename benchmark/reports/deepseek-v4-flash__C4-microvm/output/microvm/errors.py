class MicroVMError(Exception):
    """Base exception for all microvm errors."""
    pass


class LexError(MicroVMError):
    """Raised when tokenization fails."""

    def __init__(self, message: str, offset: int) -> None:
        super().__init__(message)
        self.offset = offset


class ParseError(MicroVMError):
    """Raised when parsing fails."""

    def __init__(self, message: str, offset: int) -> None:
        super().__init__(message)
        self.offset = offset


class CompileError(MicroVMError):
    """Raised when compilation fails (e.g., duplicate declaration, undeclared name)."""
    pass


class SerializationError(MicroVMError):
    """Raised on malformed binary data or serialization issues."""
    pass


class VMRuntimeError(MicroVMError):
    """Raised when a runtime error occurs during execution."""
    pass


class StepLimitError(VMRuntimeError):
    """Raised when the step limit is exceeded."""
    pass