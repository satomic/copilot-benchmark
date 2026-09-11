"""Exception hierarchy for microvm."""


class MicroVMError(Exception):
    """Base class of every error raised by microvm."""


class _OffsetError(MicroVMError):
    def __init__(self, message: str, offset: int) -> None:
        super().__init__(f"{message} (at offset {offset})")
        self.offset = offset


class LexError(_OffsetError):
    """Malformed token; carries a zero-based ``offset``."""


class ParseError(_OffsetError):
    """Malformed program; carries a zero-based ``offset``."""


class CompileError(MicroVMError):
    """Semantic error detected at compile time (undeclared / redeclared names)."""


class SerializationError(MicroVMError):
    """Malformed or unrepresentable binary program."""


class VMRuntimeError(MicroVMError):
    """Error raised while executing bytecode."""


class StepLimitError(VMRuntimeError):
    """The step budget was exceeded."""
