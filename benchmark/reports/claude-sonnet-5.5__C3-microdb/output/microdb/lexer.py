"""Lexer for the microdb query language."""

import dataclasses

from .errors import LexError

KEYWORDS = frozenset(
    "SELECT DISTINCT FROM INNER LEFT JOIN ON WHERE GROUP BY HAVING ORDER ASC DESC "
    "LIMIT OFFSET AS AND OR NOT IS NULL TRUE FALSE".split()
)
_DIGITS = "0123456789"
_IDENT_START = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ_"
_IDENT_PART = _IDENT_START + _DIGITS
_SPACE = " \t\r\n\f\v"
_TWO_CHAR_OPS = ("<=", ">=", "<>")
_ONE_CHAR_OPS = "=<>+-*/%(),."


@dataclasses.dataclass(frozen=True)
class Token:
    kind: str  # INT FLOAT TEXT IDENT KW OP EOF
    value: object
    start: int
    end: int


def _read_text(source: str, i: int) -> tuple[Token, int]:
    n = len(source)
    j = i + 1
    parts: list[str] = []
    while j < n:
        if source[j] == "'":
            if j + 1 < n and source[j + 1] == "'":
                parts.append("'")
                j += 2
                continue
            return Token("TEXT", "".join(parts), i, j + 1), j + 1
        parts.append(source[j])
        j += 1
    raise LexError("unterminated text literal", i)


def _skip_digits(source: str, j: int) -> int:
    while j < len(source) and source[j] in _DIGITS:
        j += 1
    return j


def _read_number(source: str, i: int) -> tuple[Token, int]:
    n = len(source)
    j = _skip_digits(source, i)
    is_float = False
    if j < n and source[j] == ".":
        is_float = True
        j = _skip_digits(source, j + 1)
    if j < n and source[j] in "eE":
        k = j + 1
        if k < n and source[k] in "+-":
            k += 1
        if k < n and source[k] in _DIGITS:
            j = _skip_digits(source, k)
            is_float = True
    text = source[i:j]
    if is_float:
        return Token("FLOAT", float(text), i, j), j
    return Token("INT", int(text), i, j), j


def _read_ident(source: str, i: int) -> tuple[Token, int]:
    j = i + 1
    while j < len(source) and source[j] in _IDENT_PART:
        j += 1
    word = source[i:j]
    if word.upper() in KEYWORDS:
        return Token("KW", word.upper(), i, j), j
    return Token("IDENT", word, i, j), j


def _read_operator(source: str, i: int) -> tuple[Token, int]:
    two = source[i:i + 2]
    if two in _TWO_CHAR_OPS:
        return Token("OP", two, i, i + 2), i + 2
    if source[i] in _ONE_CHAR_OPS:
        return Token("OP", source[i], i, i + 1), i + 1
    raise LexError(f"unexpected character {source[i]!r}", i)


def _next_token(source: str, i: int) -> tuple[Token, int]:
    ch = source[i]
    if ch == "'":
        return _read_text(source, i)
    following = source[i + 1:i + 2]
    if ch in _DIGITS or (ch == "." and following != "" and following in _DIGITS):
        return _read_number(source, i)
    if ch in _IDENT_START:
        return _read_ident(source, i)
    return _read_operator(source, i)


def tokenize(source: str) -> list[Token]:
    tokens: list[Token] = []
    i = 0
    n = len(source)
    while i < n:
        if source[i] in _SPACE:
            i += 1
        elif source.startswith("--", i):
            end = source.find("\n", i)
            i = n if end < 0 else end + 1
        else:
            token, i = _next_token(source, i)
            tokens.append(token)
    tokens.append(Token("EOF", None, n, n))
    return tokens
