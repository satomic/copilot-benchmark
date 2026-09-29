"""Exception hierarchy for microvm."""


class MicroVMError(Exception):
    """Base class of every error raised by microvm."""


class LexError(MicroVMError):
    """Raised when the source text cannot be tokenized."""

    def __init__(self, message: str, offset: int) -> None:
        super().__init__(f"{message} at offset {offset}")
        self.message = message
        self.offset = offset


class ParseError(MicroVMError):
    """Raised when the token stream is not a valid program."""

    def __init__(self, message: str, offset: int) -> None:
        super().__init__(f"{message} at offset {offset}")
        self.message = message
        self.offset = offset


class CompileError(MicroVMError):
    """Raised for static errors such as undeclared or redeclared names."""


class SerializationError(MicroVMError):
    """Raised when a program cannot be encoded or a binary cannot be decoded."""


class VMRuntimeError(MicroVMError):
    """Raised when the virtual machine hits an error while executing."""


class StepLimitError(VMRuntimeError):
    """Raised when execution exceeds its step budget."""
