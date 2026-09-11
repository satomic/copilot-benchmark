"""Exception hierarchy for minilang."""


class MiniLangError(Exception):
    """Base class for every minilang failure."""

    def __init__(self, message: str, position: int | None = None) -> None:
        super().__init__(message)
        self.position = position


class LexError(MiniLangError):
    """The source could not be split into tokens."""


class ParseError(MiniLangError):
    """The token stream is not a well-formed expression."""


class EvalError(MiniLangError):
    """The expression is well-formed but cannot be evaluated."""
