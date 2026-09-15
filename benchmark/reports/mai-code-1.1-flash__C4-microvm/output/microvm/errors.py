class MicroVMError(Exception):
    """Base class for all MicroVM errors."""


class LexError(MicroVMError):
    def __init__(self, message: str, offset: int) -> None:
        super().__init__(message)
        self.offset: int = offset


class ParseError(MicroVMError):
    def __init__(self, message: str, offset: int) -> None:
        super().__init__(message)
        self.offset: int = offset


class CompileError(MicroVMError):
    pass


class SerializationError(MicroVMError):
    pass


class VMRuntimeError(MicroVMError):
    pass


class StepLimitError(VMRuntimeError):
    pass
