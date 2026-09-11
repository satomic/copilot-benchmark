"""Exception hierarchy for minilang."""


class MiniLangError(Exception):
    """Base class for all minilang errors.

    ``position`` is a 0-based offset into the source, or ``None`` when unknown.
    ``str(error)`` is the plain message with no position prefix.
    """

    def __init__(self, message: str, position: "int | None" = None):
        super().__init__(message)
        self.message = message
        self.position = position

    def __str__(self) -> str:
        return self.message


class LexError(MiniLangError):
    """Raised by the lexer for malformed input."""


class ParseError(MiniLangError):
    """Raised by the parser for syntactically invalid input."""


class EvalError(MiniLangError):
    """Raised by the evaluator for runtime errors."""
