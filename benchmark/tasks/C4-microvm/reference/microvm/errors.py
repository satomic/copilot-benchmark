"""Exception hierarchy for microvm."""

from __future__ import annotations

__all__ = [
    "MicroVMError",
    "LexError",
    "ParseError",
    "CompileError",
    "SerializationError",
    "VMRuntimeError",
    "StepLimitError",
]


class MicroVMError(Exception):
    """Base class for every error raised by this package."""


class _PositionedError(MicroVMError):
    def __init__(self, message: str, offset: int) -> None:
        self.offset = offset
        super().__init__(f"{message} at offset {offset}")


class LexError(_PositionedError):
    """The source could not be split into tokens."""


class ParseError(_PositionedError):
    """The token stream is not a valid program."""


class CompileError(MicroVMError):
    """A name was declared twice, or used without being declared."""


class SerializationError(MicroVMError):
    """The binary form could not be produced or is malformed."""


class VMRuntimeError(MicroVMError):
    """An instruction failed while executing."""


class StepLimitError(VMRuntimeError):
    """The step budget was exceeded."""
