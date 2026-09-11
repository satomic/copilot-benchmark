class MicroVMError(Exception):
    """Base class for language, execution, and bytecode errors."""


class LexError(MicroVMError):
    def __init__(self, message: str, offset: int) -> None:
        self.offset = offset
        super().__init__(f"{message} at offset {offset}")


class ParseError(MicroVMError):
    def __init__(self, message: str, offset: int) -> None:
        self.offset = offset
        super().__init__(f"{message} at offset {offset}")


class CompileError(MicroVMError):
    pass


class SerializationError(MicroVMError):
    pass


class VMRuntimeError(MicroVMError):
    pass


class StepLimitError(VMRuntimeError):
    pass
