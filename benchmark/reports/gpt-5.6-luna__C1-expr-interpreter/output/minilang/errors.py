class MiniLangError(Exception):
    def __init__(self, message, position=None):
        super().__init__(message)
        self.position = position


class LexError(MiniLangError):
    pass


class ParseError(MiniLangError):
    pass


class EvalError(MiniLangError):
    pass
