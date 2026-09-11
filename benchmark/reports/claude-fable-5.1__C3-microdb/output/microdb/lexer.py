"""Tokenizer for the microdb query language."""

from __future__ import annotations

import dataclasses

from .errors import LexError

KEYWORDS = frozenset(
    "SELECT DISTINCT FROM INNER LEFT JOIN ON WHERE GROUP BY HAVING ORDER ASC DESC "
    "LIMIT OFFSET AS AND OR NOT IS NULL TRUE FALSE".split()
)

TWO_CHAR_OPS = ("<>", "<=", ">=")
ONE_CHAR_OPS = "=<>+-*/%(),."


@dataclasses.dataclass(frozen=True)
class Token:
    kind: str  # INT FLOAT TEXT IDENT KW OP EOF
    value: object
    offset: int
    end: int


def _is_ident_start(ch: str) -> bool:
    return ch.isascii() and (ch.isalpha() or ch == "_")


def _is_ident_char(ch: str) -> bool:
    return ch.isascii() and (ch.isalnum() or ch == "_")


def _scan_number(src: str, pos: int) -> Token:
    n = len(src)
    i = pos
    is_float = False
    while i < n and src[i].isdigit():
        i += 1
    if i < n and src[i] == ".":
        is_float = True
        i += 1
        while i < n and src[i].isdigit():
            i += 1
    if i < n and src[i] in "eE":
        j = i + 1
        if j < n and src[j] in "+-":
            j += 1
        if j < n and src[j].isdigit():
            while j < n and src[j].isdigit():
                j += 1
            i = j
            is_float = True
    text = src[pos:i]
    if is_float:
        return Token("FLOAT", float(text), pos, i)
    return Token("INT", int(text), pos, i)


def _scan_text(src: str, pos: int) -> Token:
    n = len(src)
    i = pos + 1
    parts: list[str] = []
    while True:
        if i >= n:
            raise LexError("unterminated text literal", pos)
        ch = src[i]
        if ch == "'":
            if i + 1 < n and src[i + 1] == "'":
                parts.append("'")
                i += 2
                continue
            return Token("TEXT", "".join(parts), pos, i + 1)
        parts.append(ch)
        i += 1


def _scan_word(src: str, pos: int) -> Token:
    n = len(src)
    i = pos
    while i < n and _is_ident_char(src[i]):
        i += 1
    word = src[pos:i]
    if word.upper() in KEYWORDS:
        return Token("KW", word.upper(), pos, i)
    return Token("IDENT", word, pos, i)


def tokenize(src: str) -> list[Token]:
    tokens: list[Token] = []
    n = len(src)
    i = 0
    while i < n:
        ch = src[i]
        if ch.isspace():
            i += 1
            continue
        if src.startswith("--", i):
            nl = src.find("\n", i)
            i = n if nl < 0 else nl + 1
            continue
        if ch.isdigit() or (ch == "." and i + 1 < n and src[i + 1].isdigit()):
            tok = _scan_number(src, i)
        elif ch == "'":
            tok = _scan_text(src, i)
        elif _is_ident_start(ch):
            tok = _scan_word(src, i)
        elif src[i : i + 2] in TWO_CHAR_OPS:
            tok = Token("OP", src[i : i + 2], i, i + 2)
        elif ch in ONE_CHAR_OPS:
            tok = Token("OP", ch, i, i + 1)
        else:
            raise LexError(f"unexpected character {ch!r}", i)
        tokens.append(tok)
        i = tok.end
    tokens.append(Token("EOF", None, n, n))
    return tokens
