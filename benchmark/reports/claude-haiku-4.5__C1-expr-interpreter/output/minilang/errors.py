class MiniLangError(Exception):
    """Base exception for minilang errors."""
    
    def __init__(self, message: str, position: int | None = None):
        super().__init__(message)
        self.position = position


class LexError(MiniLangError):
    """Raised when tokenization fails."""
    pass


class ParseError(MiniLangError):
    """Raised when parsing fails."""
    pass


class EvalError(MiniLangError):
    """Raised when evaluation fails."""
    pass
