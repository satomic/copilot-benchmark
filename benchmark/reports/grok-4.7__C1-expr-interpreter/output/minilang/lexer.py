"""Tokenizer for minilang expressions."""

from minilang.errors import LexError

_KEYWORDS = frozenset({"true", "false", "and", "or", "not"})
_ESCAPES = {"n": "\n", "t": "\t", "r": "\r", '"': '"', "\\": "\\"}
_SINGLE_OPS = frozenset("+-*/%^<>(),")


class Token:
    """A lexical token. ``kind`` is NUMBER, STRING, IDENT, KEYWORD, or OP."""

    def __init__(self, kind: str, value, position: int):
        self.kind = kind
        self.value = value
        self.position = position

    def __repr__(self) -> str:
        return f"Token({self.kind!r}, {self.value!r}, {self.position})"


def _is_digit(char: str) -> bool:
    return "0" <= char <= "9"


def _is_ident_start(char: str) -> bool:
    return char == "_" or "A" <= char <= "Z" or "a" <= char <= "z"


def _is_ident_cont(char: str) -> bool:
    return _is_ident_start(char) or _is_digit(char)


def _lex_string(source: str, start: int) -> tuple[str, int]:
    index = start + 1
    length = len(source)
    chars: list[str] = []
    while index < length:
        char = source[index]
        if char == "\n":
            raise LexError("unterminated string", start)
        if char == '"':
            return "".join(chars), index + 1
        if char == "\\":
            if index + 1 >= length or source[index + 1] == "\n":
                raise LexError("unterminated string", start)
            escaped = source[index + 1]
            if escaped not in _ESCAPES:
                raise LexError("invalid escape", index)
            chars.append(_ESCAPES[escaped])
            index += 2
            continue
        chars.append(char)
        index += 1
    raise LexError("unterminated string", start)


def _lex_number(source: str, start: int) -> tuple[float, int]:
    """Scan a number. A trailing dot (``1.``) is a LexError."""
    index = start
    length = len(source)
    if source[index] == ".":
        index += 1
        if index >= length or not _is_digit(source[index]):
            raise LexError("invalid number", start)
        while index < length and _is_digit(source[index]):
            index += 1
    else:
        while index < length and _is_digit(source[index]):
            index += 1
        if index < length and source[index] == ".":
            dot = index
            if index + 1 < length and _is_digit(source[index + 1]):
                index += 1
                while index < length and _is_digit(source[index]):
                    index += 1
            elif index + 1 < length and source[index + 1] in "eE":
                # ``1.e3`` does not end in a dot; only a trailing dot (``1.``) is invalid.
                index += 1
            else:
                raise LexError("invalid number", dot)
    if index < length and source[index] in "eE":
        index += 1
        if index < length and source[index] in "+-":
            index += 1
        if index >= length or not _is_digit(source[index]):
            raise LexError("invalid number", start)
        while index < length and _is_digit(source[index]):
            index += 1
    text = source[start:index]
    try:
        value = float(text)
    except ValueError:
        raise LexError("invalid number", start) from None
    return value, index


def tokenize(source: str) -> list:
    """Return tokens for ``source``. Whitespace and comments are discarded."""
    tokens: list[Token] = []
    index = 0
    length = len(source)
    while index < length:
        char = source[index]
        if char in " \t\n\r":
            index += 1
            continue
        if char == "#":
            index += 1
            while index < length and source[index] != "\n":
                index += 1
            continue
        if char == '"':
            start = index
            value, index = _lex_string(source, start)
            tokens.append(Token("STRING", value, start))
            continue
        if _is_digit(char) or (
            char == "." and index + 1 < length and _is_digit(source[index + 1])
        ):
            start = index
            value, index = _lex_number(source, start)
            tokens.append(Token("NUMBER", value, start))
            continue
        if char == ".":
            raise LexError("invalid number", index)
        if _is_ident_start(char):
            start = index
            index += 1
            while index < length and _is_ident_cont(source[index]):
                index += 1
            text = source[start:index]
            kind = "KEYWORD" if text in _KEYWORDS else "IDENT"
            tokens.append(Token(kind, text, start))
            continue
        if char == "=":
            if index + 1 < length and source[index + 1] == "=":
                tokens.append(Token("OP", "==", index))
                index += 2
                continue
            raise LexError("unexpected '='", index)
        if char in "!<>":
            if index + 1 < length and source[index + 1] == "=":
                tokens.append(Token("OP", char + "=", index))
                index += 2
                continue
            if char == "!":
                raise LexError("unexpected character", index)
            tokens.append(Token("OP", char, index))
            index += 1
            continue
        if char in _SINGLE_OPS:
            tokens.append(Token("OP", char, index))
            index += 1
            continue
        raise LexError("unexpected character", index)
    return tokens
