"""Exception hierarchy for minilang."""


class MiniLangError(Exception):
    """Base error. ``position`` is a 0-based source offset, or None."""

    def __init__(self, message: str = "", position: int | None = None):
        super().__init__(message)
        self.position = position


class LexError(MiniLangError):
    """Invalid token or character in the source."""


class ParseError(MiniLangError):
    """Source does not match the expression grammar."""


class EvalError(MiniLangError):
    """Runtime failure while evaluating an expression."""
