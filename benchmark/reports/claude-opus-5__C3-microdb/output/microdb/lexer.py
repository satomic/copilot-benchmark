"""Lexer for the microdb query language."""

from __future__ import annotations

import dataclasses

from .errors import LexError

KEYWORDS: frozenset[str] = frozenset(
    {
        "SELECT", "DISTINCT", "FROM", "INNER", "LEFT", "JOIN", "ON", "WHERE",
        "GROUP", "BY", "HAVING", "ORDER", "ASC", "DESC", "LIMIT", "OFFSET",
        "AS", "AND", "OR", "NOT", "IS", "NULL", "TRUE", "FALSE",
    }
)

TWO_CHAR_OPERATORS: tuple[str, ...] = ("<>", "<=", ">=")
ONE_CHAR_OPERATORS: str = "=<>+-*/%(),."

INT_TOKEN: str = "INT"
FLOAT_TOKEN: str = "FLOAT"
TEXT_TOKEN: str = "TEXT"
IDENT_TOKEN: str = "IDENT"
KEYWORD_TOKEN: str = "KEYWORD"
OP_TOKEN: str = "OP"
EOF_TOKEN: str = "EOF"


@dataclasses.dataclass(frozen=True)
class Token:
    """A lexical token with its zero-based source offset."""

    kind: str
    value: object
    offset: int
    text: str


def _is_ident_start(ch: str) -> bool:
    return ch.isascii() and (ch.isalpha() or ch == "_")


def _is_ident_part(ch: str) -> bool:
    return ch.isascii() and (ch.isalnum() or ch == "_")


def _skip_ignorable(src: str, i: int) -> int:
    """Advance past whitespace and ``--`` comments, returning the new index."""
    n = len(src)
    while i < n:
        if src[i].isspace():
            i += 1
        elif src.startswith("--", i):
            while i < n and src[i] != "\n":
                i += 1
        else:
            break
    return i


def _lex_text(src: str, start: int) -> tuple[Token, int]:
    """Lex a single-quoted text literal; ``''`` denotes an embedded quote."""
    i = start + 1
    chars: list[str] = []
    n = len(src)
    while i < n:
        if src[i] == "'":
            if i + 1 < n and src[i + 1] == "'":
                chars.append("'")
                i += 2
                continue
            return Token(TEXT_TOKEN, "".join(chars), start, src[start : i + 1]), i + 1
        chars.append(src[i])
        i += 1
    raise LexError("unterminated text literal", start)


def _scan_digits(src: str, i: int) -> int:
    while i < len(src) and src[i].isdigit():
        i += 1
    return i


def _lex_number(src: str, start: int) -> tuple[Token, int]:
    """Lex an integer or float literal, including forms like ``1.`` and ``.5e-2``."""
    n = len(src)
    i = _scan_digits(src, start)
    is_float = False
    if i < n and src[i] == ".":
        is_float = True
        i = _scan_digits(src, i + 1)
    if i < n and src[i] in "eE":
        j = i + 1
        if j < n and src[j] in "+-":
            j += 1
        if j < n and src[j].isdigit():
            is_float = True
            i = _scan_digits(src, j)
    text = src[start:i]
    if is_float:
        return Token(FLOAT_TOKEN, float(text), start, text), i
    return Token(INT_TOKEN, int(text), start, text), i


def _lex_word(src: str, start: int) -> tuple[Token, int]:
    i = start
    while i < len(src) and _is_ident_part(src[i]):
        i += 1
    text = src[start:i]
    upper = text.upper()
    if upper in KEYWORDS:
        return Token(KEYWORD_TOKEN, upper, start, text), i
    return Token(IDENT_TOKEN, text, start, text), i


def _lex_operator(src: str, start: int) -> tuple[Token, int]:
    for candidate in TWO_CHAR_OPERATORS:
        if src.startswith(candidate, start):
            return Token(OP_TOKEN, candidate, start, candidate), start + 2
    ch = src[start]
    if ch in ONE_CHAR_OPERATORS:
        return Token(OP_TOKEN, ch, start, ch), start + 1
    raise LexError(f"unexpected character {ch!r}", start)


def tokenize(src: str) -> list[Token]:
    """Split ``src`` into tokens, ending with a single EOF token."""
    tokens: list[Token] = []
    i = 0
    n = len(src)
    while True:
        i = _skip_ignorable(src, i)
        if i >= n:
            break
        ch = src[i]
        if ch == "'":
            token, i = _lex_text(src, i)
        elif ch.isdigit() or (ch == "." and i + 1 < n and src[i + 1].isdigit()):
            token, i = _lex_number(src, i)
        elif _is_ident_start(ch):
            token, i = _lex_word(src, i)
        else:
            token, i = _lex_operator(src, i)
        tokens.append(token)
    tokens.append(Token(EOF_TOKEN, None, n, ""))
    return tokens
