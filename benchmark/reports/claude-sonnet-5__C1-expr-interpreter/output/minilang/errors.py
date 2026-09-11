"""Exception hierarchy for minilang."""


class MiniLangError(Exception):
    """Base class for all minilang errors.

    ``position`` is the 0-based offset into the source string of the
    offending character/token, or ``None`` when no position is available
    (this is always the case for EvalError, which happens after parsing).
    """

    def __init__(self, message: str, position: int | None = None):
        super().__init__(message)
        self.message = message
        self.position = position

    def __str__(self) -> str:
        # No position prefix: str(error) must be the plain message.
        return self.message


class LexError(MiniLangError):
    pass


class ParseError(MiniLangError):
    pass


class EvalError(MiniLangError):
    pass
