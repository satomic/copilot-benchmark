class MicroVMError(Exception):
    """Base class for language and runtime failures."""


class LexError(MicroVMError):
    offset: int

    def __init__(self, message: str, offset: int) -> None:
        super().__init__(message)
        self.offset = offset


class ParseError(MicroVMError):
    offset: int

    def __init__(self, message: str, offset: int) -> None:
        super().__init__(message)
        self.offset = offset


class CompileError(MicroVMError):
    pass


class SerializationError(MicroVMError):
    pass


class VMRuntimeError(MicroVMError):
    pass


class StepLimitError(VMRuntimeError):
    pass
