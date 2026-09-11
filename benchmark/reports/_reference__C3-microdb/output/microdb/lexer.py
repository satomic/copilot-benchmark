"""Tokenizer for the query language."""

from __future__ import annotations

import dataclasses
import re

from .errors import LexError

__all__ = ["Token", "KEYWORDS", "tokenize"]

KEYWORDS = frozenset(
    """SELECT DISTINCT FROM INNER LEFT JOIN ON WHERE GROUP BY HAVING ORDER ASC DESC
    LIMIT OFFSET AS AND OR NOT IS NULL TRUE FALSE""".split()
)

#: Longest operators first so that <= and <> win over <.
_OPERATORS = ("<=", ">=", "<>", "=", "<", ">", "+", "-", "*", "/", "%", "(", ")", ",", ".")

_IDENT_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
#: digits with optional fraction and optional exponent, or a bare fraction like .5
_NUMBER_RE = re.compile(r"(?:\d+\.\d*|\.\d+|\d+)(?:[eE][+-]?\d+)?")


@dataclasses.dataclass(frozen=True)
class Token:
    kind: str  # KEYWORD IDENT INT FLOAT TEXT OP
    text: str
    value: object
    offset: int


def _read_text_literal(src: str, start: int) -> tuple[str, int]:
    """Read a single-quoted literal starting at the opening quote."""
    parts: list[str] = []
    index = start + 1
    while True:
        if index >= len(src):
            raise LexError("unterminated text literal", start)
        char = src[index]
        if char == "'":
            if index + 1 < len(src) and src[index + 1] == "'":
                parts.append("'")
                index += 2
                continue
            return "".join(parts), index + 1
        parts.append(char)
        index += 1


def _is_float(text: str) -> bool:
    return "." in text or "e" in text.lower()


def tokenize(src: str) -> list[Token]:
    """Split ``src`` into tokens. Raises :class:`LexError` with a character offset."""
    tokens: list[Token] = []
    index = 0
    while index < len(src):
        char = src[index]
        if char.isspace():
            index += 1
            continue
        if src.startswith("--", index):
            newline = src.find("\n", index)
            index = len(src) if newline < 0 else newline + 1
            continue
        if char == "'":
            text, index = _read_text_literal(src, index)
            tokens.append(Token("TEXT", text, text, index))
            continue
        number = _NUMBER_RE.match(src, index)
        if number and (char.isdigit() or (char == "." and number.end() > index + 1)):
            raw = number.group(0)
            if _is_float(raw):
                tokens.append(Token("FLOAT", raw, float(raw), index))
            else:
                tokens.append(Token("INT", raw, int(raw), index))
            index = number.end()
            continue
        ident = _IDENT_RE.match(src, index)
        if ident:
            raw = ident.group(0)
            upper = raw.upper()
            if upper in KEYWORDS:
                tokens.append(Token("KEYWORD", upper, upper, index))
            else:
                tokens.append(Token("IDENT", raw, raw, index))
            index = ident.end()
            continue
        for op in _OPERATORS:
            if src.startswith(op, index):
                tokens.append(Token("OP", op, op, index))
                index += len(op)
                break
        else:
            raise LexError(f"unexpected character {char!r}", index)
    return tokens
