"""Exception hierarchy for the microvm toolchain."""

from __future__ import annotations


class MicroVMError(Exception):
    """Base class for every error raised by this package."""


class LexError(MicroVMError):
    """Raised when the source text cannot be tokenized."""

    def __init__(self, message: str, offset: int) -> None:
        super().__init__(message)
        self.offset: int = offset


class ParseError(MicroVMError):
    """Raised when the token stream is not a valid program."""

    def __init__(self, message: str, offset: int) -> None:
        super().__init__(message)
        self.offset: int = offset


class CompileError(MicroVMError):
    """Raised for static (compile time) errors such as unknown names."""


class SerializationError(MicroVMError):
    """Raised when a program cannot be encoded or a blob cannot be decoded."""


class VMRuntimeError(MicroVMError):
    """Raised when an instruction fails at run time."""


class StepLimitError(VMRuntimeError):
    """Raised when execution exceeds the configured step budget."""
