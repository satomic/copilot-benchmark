"""Lexer: turns query text into a list of tokens."""

from __future__ import annotations

import dataclasses

from .errors import LexError

KEYWORDS = frozenset(
    "SELECT DISTINCT FROM INNER LEFT JOIN ON WHERE GROUP BY HAVING ORDER ASC DESC "
    "LIMIT OFFSET AS AND OR NOT IS NULL TRUE FALSE".split()
)

_TWO_CHAR_OPS = ("<>", "<=", ">=")
_ONE_CHAR_OPS = "=<>+-*/%(),."


@dataclasses.dataclass(frozen=True)
class Token:
    kind: str  # "INT" | "FLOAT" | "TEXT" | "IDENT" | "KEYWORD" | "OP" | "EOF"
    value: object
    offset: int
    end: int


def _is_ident_start(c: str) -> bool:
    return c == "_" or ("a" <= c <= "z") or ("A" <= c <= "Z")


def _is_ident_char(c: str) -> bool:
    return _is_ident_start(c) or _is_digit(c)


def _is_digit(c: str) -> bool:
    return "0" <= c <= "9"


def _digits_end(text: str, i: int) -> int:
    while i < len(text) and _is_digit(text[i]):
        i += 1
    return i


def _lex_number(text: str, start: int) -> Token:
    i = _digits_end(text, start)
    is_float = False
    if i < len(text) and text[i] == ".":
        is_float = True
        i = _digits_end(text, i + 1)
    if i < len(text) and text[i] in "eE":
        j = i + 1
        if j < len(text) and text[j] in "+-":
            j += 1
        if j < len(text) and _is_digit(text[j]):
            is_float = True
            i = _digits_end(text, j)
    raw = text[start:i]
    if is_float:
        return Token("FLOAT", float(raw), start, i)
    return Token("INT", int(raw), start, i)


def _lex_text(text: str, start: int) -> Token:
    i = start + 1
    parts: list[str] = []
    while True:
        j = text.find("'", i)
        if j < 0:
            raise LexError("unterminated text literal", start)
        parts.append(text[i:j])
        if j + 1 < len(text) and text[j + 1] == "'":
            parts.append("'")
            i = j + 2
            continue
        return Token("TEXT", "".join(parts), start, j + 1)


def _lex_word(text: str, start: int) -> Token:
    i = start
    while i < len(text) and _is_ident_char(text[i]):
        i += 1
    word = text[start:i]
    if word.upper() in KEYWORDS:
        return Token("KEYWORD", word.upper(), start, i)
    return Token("IDENT", word, start, i)


def _skip_space(text: str, i: int) -> int:
    while i < len(text):
        c = text[i]
        if c.isspace():
            i += 1
        elif text.startswith("--", i):
            nl = text.find("\n", i)
            i = len(text) if nl < 0 else nl + 1
        else:
            break
    return i


def _next_token(text: str, i: int) -> Token:
    c = text[i]
    if _is_digit(c) or (c == "." and i + 1 < len(text) and _is_digit(text[i + 1])):
        return _lex_number(text, i)
    if c == "'":
        return _lex_text(text, i)
    if _is_ident_start(c):
        return _lex_word(text, i)
    two = text[i : i + 2]
    if two in _TWO_CHAR_OPS:
        return Token("OP", two, i, i + 2)
    if c in _ONE_CHAR_OPS:
        return Token("OP", c, i, i + 1)
    raise LexError(f"unexpected character {c!r}", i)


def tokenize(text: str) -> list[Token]:
    """Tokenize query text; the result always ends with an EOF token."""
    tokens: list[Token] = []
    i = _skip_space(text, 0)
    while i < len(text):
        tok = _next_token(text, i)
        tokens.append(tok)
        i = _skip_space(text, tok.end)
    tokens.append(Token("EOF", None, len(text), len(text)))
    return tokens
