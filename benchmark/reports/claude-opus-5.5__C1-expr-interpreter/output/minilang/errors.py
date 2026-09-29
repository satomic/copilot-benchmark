"""Exception hierarchy for minilang."""


class MiniLangError(Exception):
    """Base class; ``str(err)`` is the plain message."""

    def __init__(self, message, position=None):
        super().__init__(message)
        self.message = message
        self.position = position

    def __str__(self):
        return self.message


class LexError(MiniLangError):
    pass


class ParseError(MiniLangError):
    pass


class EvalError(MiniLangError):
    pass
