class MiniLangError(Exception):
    position: int | None

    def __init__(self, message: str, position: int | None = None) -> None:
        super().__init__(message)
        self.position = position


class LexError(MiniLangError):
    pass


class ParseError(MiniLangError):
    pass


class EvalError(MiniLangError):
    pass
