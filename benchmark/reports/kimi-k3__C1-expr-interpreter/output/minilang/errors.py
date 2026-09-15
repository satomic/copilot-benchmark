"""Exception hierarchy for minilang."""


class MiniLangError(Exception):
    """Base class for all minilang errors.

    ``position`` is the 0-based offset into the source of the offending
    character or token, or None when not applicable (e.g. EvalError).
    """

    def __init__(self, message, position=None):
        super().__init__(message)
        self.message = message
        self.position = position

    def __str__(self):
        # Plain message only: no position prefix (rule 29).
        return self.message


class LexError(MiniLangError):
    """Raised while tokenizing."""


class ParseError(MiniLangError):
    """Raised while parsing."""


class EvalError(MiniLangError):
    """Raised while evaluating."""
