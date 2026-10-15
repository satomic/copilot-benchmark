"""Hand-written lexer: turns query text into a list of tokens."""

from __future__ import annotations

import re
from dataclasses import dataclass

from .errors import LexError

KEYWORDS = frozenset({
    "SELECT", "DISTINCT", "FROM", "INNER", "LEFT", "JOIN", "ON", "WHERE",
    "GROUP", "BY", "HAVING", "ORDER", "ASC", "DESC", "LIMIT", "OFFSET",
    "AS", "AND", "OR", "NOT", "IS", "NULL", "TRUE", "FALSE",
})

_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
# digits.digits | digits. | .digits | digits, each with an optional exponent
_NUMBER = re.compile(r"(?:[0-9]+\.[0-9]*|\.[0-9]+|[0-9]+)(?:[eE][+-]?[0-9]+)?")
_TWO_CHAR_OPS = ("<>", "<=", ">=")
_ONE_CHAR_OPS = frozenset("=<>+-*/%(),.")


@dataclass(frozen=True)
class Token:
    """kind is INT, FLOAT, TEXT, IDENT, KW, OP or EOF; offsets are zero-based."""

    kind: str
    value: object
    offset: int
    end: int


def tokenize(source: str) -> list[Token]:
    """Split source into tokens, always ending with an EOF token."""
    tokens: list[Token] = []
    pos = 0
    while True:
        pos = _skip_blank(source, pos)
        if pos >= len(source):
            tokens.append(Token("EOF", None, pos, pos))
            return tokens
        tok = _lex_one(source, pos)
        tokens.append(tok)
        pos = tok.end


def _skip_blank(source: str, pos: int) -> int:
    """Skip whitespace and ``--`` line comments."""
    n = len(source)
    while pos < n:
        if source[pos].isspace():
            pos += 1
        elif source.startswith("--", pos):
            newline = source.find("\n", pos)
            pos = n if newline < 0 else newline + 1
        else:
            break
    return pos


def _lex_one(source: str, pos: int) -> Token:
    ch = source[pos]
    if ch == "'":
        return _lex_text(source, pos)
    match = _NUMBER.match(source, pos)
    if match:
        return _number_token(match.group(), pos, match.end())
    match = _IDENT.match(source, pos)
    if match:
        word = match.group()
        upper = word.upper()
        kind, value = ("KW", upper) if upper in KEYWORDS else ("IDENT", word)
        return Token(kind, value, pos, match.end())
    two = source[pos:pos + 2]
    if two in _TWO_CHAR_OPS:
        return Token("OP", two, pos, pos + 2)
    if ch in _ONE_CHAR_OPS:
        return Token("OP", ch, pos, pos + 1)
    raise LexError(f"unexpected character {ch!r} at offset {pos}", pos)


def _number_token(text: str, pos: int, end: int) -> Token:
    if "." in text or "e" in text.lower():
        return Token("FLOAT", float(text), pos, end)
    return Token("INT", int(text), pos, end)


def _lex_text(source: str, pos: int) -> Token:
    """Lex a single-quoted literal in which '' stands for one quote."""
    chars: list[str] = []
    i = pos + 1
    n = len(source)
    while i < n:
        if source[i] == "'":
            if i + 1 < n and source[i + 1] == "'":
                chars.append("'")
                i += 2
                continue
            return Token("TEXT", "".join(chars), pos, i + 1)
        chars.append(source[i])
        i += 1
    raise LexError(f"unterminated text literal at offset {pos}", pos)
