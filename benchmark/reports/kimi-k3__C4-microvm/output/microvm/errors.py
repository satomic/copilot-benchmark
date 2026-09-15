"""Exception hierarchy for the microvm language toolchain."""


class MicroVMError(Exception):
    """Base class for every error raised by microvm."""


class LexError(MicroVMError):
    """Raised when tokenization fails; carries a zero-based ``offset``."""

    def __init__(self, message: str, offset: int) -> None:
        super().__init__(message)
        self.offset = offset


class ParseError(MicroVMError):
    """Raised when parsing fails; carries a zero-based ``offset``."""

    def __init__(self, message: str, offset: int) -> None:
        super().__init__(message)
        self.offset = offset


class CompileError(MicroVMError):
    """Raised when a program is structurally invalid at compile time."""


class SerializationError(MicroVMError):
    """Raised when encoding or decoding a binary program fails."""


class VMRuntimeError(MicroVMError):
    """Raised when execution violates a run-time rule."""


class StepLimitError(VMRuntimeError):
    """Raised when the executed instruction count exceeds the step limit."""
