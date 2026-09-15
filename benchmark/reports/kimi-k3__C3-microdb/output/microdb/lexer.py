"""Lexer for the microdb query language."""

from __future__ import annotations

import dataclasses

from .errors import LexError

KEYWORDS = frozenset(
    "SELECT DISTINCT FROM INNER LEFT JOIN ON WHERE GROUP BY HAVING ORDER "
    "ASC DESC LIMIT OFFSET AS AND OR NOT IS NULL TRUE FALSE".split()
)

_OPS2 = ("<>", "<=", ">=")
_OPS1 = set("=<>+-*/%(),.")


@dataclasses.dataclass(frozen=True)
class Token:
    kind: str  # "INT" | "FLOAT" | "TEXT" | "IDENT" | "KW" | "OP" | "EOF"
    value: object  # literal value, uppercased keyword, identifier, or operator
    offset: int  # zero-based character offset of the token start
    text: str  # raw source slice

    @property
    def end(self) -> int:
        """Offset just past the token."""
        return self.offset + len(self.text)


def tokenize(text: str) -> list[Token]:
    """Split query text into tokens; raises LexError on invalid input."""
    tokens: list[Token] = []
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if ch in " \t\r\n":
            i += 1
        elif ch == "-" and text.startswith("--", i):
            nl = text.find("\n", i)
            i = n if nl == -1 else nl + 1
        elif ch == "'":
            tok, i = _lex_text(text, i)
            tokens.append(tok)
        elif ch.isdigit() or (ch == "." and i + 1 < n and text[i + 1].isdigit()):
            tok, i = _lex_number(text, i)
            tokens.append(tok)
        elif ch.isalpha() or ch == "_":
            tok, i = _lex_word(text, i)
            tokens.append(tok)
        else:
            tok, i = _lex_operator(text, i)
            tokens.append(tok)
    tokens.append(Token("EOF", None, n, ""))
    return tokens


def _lex_text(text: str, i: int) -> tuple[Token, int]:
    """Lex a single-quoted text literal; '' is an escaped quote."""
    start = i
    i += 1
    chars: list[str] = []
    n = len(text)
    while i < n:
        ch = text[i]
        if ch == "'":
            if i + 1 < n and text[i + 1] == "'":
                chars.append("'")
                i += 2
            else:
                i += 1
                return Token("TEXT", "".join(chars), start, text[start:i]), i
        else:
            chars.append(ch)
            i += 1
    raise LexError("unterminated text literal", start)


def _lex_number(text: str, i: int) -> tuple[Token, int]:
    """Lex an integer or float literal (floats may carry an exponent)."""
    start = i
    n = len(text)
    is_float = False
    while i < n and text[i].isdigit():
        i += 1
    if i < n and text[i] == ".":
        is_float = True
        i += 1
        while i < n and text[i].isdigit():
            i += 1
    if i < n and text[i] in "eE":
        j = i + 1
        if j < n and text[j] in "+-":
            j += 1
        if j < n and text[j].isdigit():
            is_float = True
            i = j
            while i < n and text[i].isdigit():
                i += 1
    raw = text[start:i]
    if is_float:
        return Token("FLOAT", float(raw), start, raw), i
    return Token("INT", int(raw), start, raw), i


def _lex_word(text: str, i: int) -> tuple[Token, int]:
    """Lex an identifier or keyword (keywords match case insensitively)."""
    start = i
    n = len(text)
    while i < n and (text[i].isalnum() or text[i] == "_"):
        i += 1
    raw = text[start:i]
    upper = raw.upper()
    if upper in KEYWORDS:
        return Token("KW", upper, start, raw), i
    return Token("IDENT", raw, start, raw), i


def _lex_operator(text: str, i: int) -> tuple[Token, int]:
    """Lex an operator or punctuation token."""
    two = text[i : i + 2]
    if two in _OPS2:
        return Token("OP", two, i, two), i + 2
    ch = text[i]
    if ch in _OPS1:
        return Token("OP", ch, i, ch), i + 1
    raise LexError(f"unexpected character {ch!r}", i)
