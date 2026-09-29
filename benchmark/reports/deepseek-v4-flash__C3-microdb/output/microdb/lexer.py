"""Tokeniser for the microdb query language."""

import re
from dataclasses import dataclass
from typing import Any

from microdb.errors import LexError

# ── Token type constants ───────────────────────────────────────────────

INT = "INT"
FLOAT = "FLOAT"
TEXT = "TEXT"
IDENTIFIER = "IDENTIFIER"
KEYWORD = "KEYWORD"
OPERATOR = "OPERATOR"
EOF = "EOF"

# Keywords (matched case-insensitively)
_KEYWORDS = frozenset(
    {
        "SELECT", "DISTINCT", "FROM", "INNER", "LEFT", "JOIN", "ON",
        "WHERE", "GROUP", "BY", "HAVING", "ORDER", "ASC", "DESC",
        "LIMIT", "OFFSET", "AS", "AND", "OR", "NOT", "IS", "NULL",
        "TRUE", "FALSE",
    }
)

# Single-char operators
_SINGLE_OPS = {"=", "<", ">", "+", "-", "*", "/", "%", "(", ")", ",", "."}

# Multi-char operators
_MULTI_OPS = {"<>", "<=", ">="}


@dataclass
class Token:
    """A single token returned by the lexer."""

    type: str
    value: Any
    offset: int

    def __repr__(self) -> str:
        return f"Token({self.type}, {self.value!r}, {self.offset})"


def _build_regex() -> re.Pattern:
    """Build a regex that matches the next token.  Order matters."""
    parts: list[tuple[str, str]] = [
        # Whitespace (skip)
        ("WS", r"[ \t\n\r]+"),
        # Line comment
        ("COMMENT", r"--[^\n]*"),
        # Text literal
        ("TEXT", r"'((?:[^']|'')*)'"),
        # Float: digits.digits, digits., .digits, all with optional exponent
        ("FLOAT", r"\d+\.\d*([eE][+-]?\d+)?|\.\d+([eE][+-]?\d+)?"),
        # Integer
        ("INT", r"\d+"),
        # Multi-char operators (must check before single-char)
        ("MULTI_OP", r"<>|<=|>="),
        # Single-char operators
        ("SINGLE_OP", r"[=<>+\-*/%( ),.]"),
        # Identifier or keyword
        ("IDENT", r"[A-Za-z_][A-Za-z0-9_]*"),
    ]
    combined = "|".join(f"(?P<{name}>{pattern})" for name, pattern in parts)
    return re.compile(combined, re.DOTALL)


_RE = _build_regex()


def _tokenize_ident(tokens: list[Token], text: str, pos: int) -> int:
    """Handle an identifier or keyword token."""
    upper = text.upper()
    if upper in _KEYWORDS:
        if upper == "TRUE":
            tokens.append(Token(TEXT, True, pos))
        elif upper == "FALSE":
            tokens.append(Token(TEXT, False, pos))
        else:
            tokens.append(Token(KEYWORD, upper, pos))
    else:
        tokens.append(Token(IDENTIFIER, text, pos))
    return pos + len(text)


def tokenize(source: str) -> list[Token]:
    """Tokenize the source string into a list of Tokens.

    Raises LexError with a zero-based offset on invalid characters.
    """
    tokens: list[Token] = []
    pos = 0

    while pos < len(source):
        m = _RE.match(source, pos)
        if m is None:
            # Try to skip newline/space if present (shouldn't happen)
            raise LexError(f"unexpected character: {source[pos]!r}", pos)

        kind = m.lastgroup
        text = m.group()

        if kind == "WS" or kind == "COMMENT":
            pos = m.end()
            continue

        if kind == "TEXT":
            # Strip surrounding quotes and replace '' with '
            inner = text[1:-1].replace("''", "'")
            tokens.append(Token(TEXT, inner, pos))
            pos = m.end()
            continue

        if kind == "FLOAT":
            tokens.append(Token(FLOAT, text, pos))
            pos = m.end()
            continue

        if kind == "INT":
            tokens.append(Token(INT, int(text), pos))
            pos = m.end()
            continue

        if kind == "MULTI_OP":
            tokens.append(Token(OPERATOR, text, pos))
            pos = m.end()
            continue

        if kind == "SINGLE_OP":
            tokens.append(Token(OPERATOR, text, pos))
            pos = m.end()
            continue

        if kind == "IDENT":
                    pos = _tokenize_ident(tokens, text, pos)
                    continue

        # Should not reach here
        raise LexError(f"unexpected character: {source[pos]!r}", pos)

    tokens.append(Token(EOF, None, pos))
    return tokens