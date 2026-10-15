"""Exception hierarchy for MicroVM."""


class MicroVMError(Exception):
    """Base class for every error raised by MicroVM."""


class LexError(MicroVMError):
    """Invalid character or token; ``offset`` is zero-based."""

    def __init__(self, message: str, offset: int) -> None:
        super().__init__(f"{message} at offset {offset}")
        self.offset: int = offset


class ParseError(MicroVMError):
    """Malformed program; ``offset`` is zero-based."""

    def __init__(self, message: str, offset: int) -> None:
        super().__init__(f"{message} at offset {offset}")
        self.offset: int = offset


class CompileError(MicroVMError):
    """Semantic error detected at compile time (names, redeclarations)."""


class SerializationError(MicroVMError):
    """Invalid input to or output from the binary codec."""


class VMRuntimeError(MicroVMError):
    """Error raised while executing a program."""


class StepLimitError(VMRuntimeError):
    """The program executed more instructions than the step limit allows."""
