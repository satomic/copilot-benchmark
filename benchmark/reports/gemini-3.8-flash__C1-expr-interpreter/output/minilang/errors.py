"""MiniLang exception hierarchy."""

class MiniLangError(Exception):
    """Base exception for all MiniLang errors."""
    def __init__(self, message: str, position: int | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.position = position

    def __str__(self) -> str:
        return self.message


class LexError(MiniLangError):
    """Raised when tokenization fails."""
    pass


class ParseError(MiniLangError):
    """Raised when parsing fails."""
    pass


class EvalError(MiniLangError):
    """Raised when evaluation fails."""
    pass
