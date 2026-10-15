from __future__ import annotations


class MicroVMError(Exception):
    """Base exception for all microvm errors."""


class LexError(MicroVMError):
    """Raised when lexical analysis fails."""

    def __init__(self, message: str, offset: int) -> None:
        super().__init__(message)
        self.offset: int = offset


class ParseError(MicroVMError):
    """Raised when parsing fails."""

    def __init__(self, message: str, offset: int) -> None:
        super().__init__(message)
        self.offset: int = offset


class CompileError(MicroVMError):
    """Raised when compilation fails."""


class SerializationError(MicroVMError):
    """Raised when binary serialization or deserialization fails."""


class VMRuntimeError(MicroVMError):
    """Raised when VM execution fails at runtime."""


class StepLimitError(VMRuntimeError):
    """Raised when VM execution exceeds the step limit."""
