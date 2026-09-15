class MiniLangError(Exception):
    def __init__(self, message: str, position: int | None = None):
        super().__init__(message)
        self.message = message
        self.position = position

    def __str__(self) -> str:
        return self.message


class LexError(MiniLangError):
    pass


class ParseError(MiniLangError):
    pass


class EvalError(MiniLangError):
    pass
