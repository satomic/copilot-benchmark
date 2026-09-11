"""Tokenizer. Lowercase keywords, case-sensitive identifiers, no EOF token."""

from __future__ import annotations

import dataclasses
import re

from .errors import LexError

__all__ = ["Token", "KEYWORDS", "tokenize"]

KEYWORDS = frozenset("let print if else while true false and or not".split())

#: Longest first so == beats =.
_OPERATORS = ("==", "!=", "<=", ">=", "+", "-", "*", "/", "%", "(", ")", "{", "}", ";", "=", "<", ">")

_IDENT_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
#: digits '.' digits, optional exponent. Bare `1.` or `.5` deliberately do not match.
_FLOAT_RE = re.compile(r"\d+\.\d+(?:[eE][+-]?\d+)?")
_INT_RE = re.compile(r"\d+")

_ESCAPES = {"n": "\n", "t": "\t", '"': '"', "\\": "\\"}


@dataclasses.dataclass(frozen=True)
class Token:
    kind: str
    text: str
    value: object
    offset: int


def _read_string(src: str, start: int) -> tuple[str, int]:
    """Read a double-quoted literal starting at the opening quote."""
    parts: list[str] = []
    index = start + 1
    while True:
        if index >= len(src):
            raise LexError("unterminated string", start)
        char = src[index]
        if char == '"':
            return "".join(parts), index + 1
        if char == "\n":
            raise LexError("newline inside string", index)
        if char == "\\":
            if index + 1 >= len(src):
                raise LexError("unterminated escape", index)
            escape = src[index + 1]
            if escape not in _ESCAPES:
                raise LexError(f"unknown escape \\{escape}", index)
            parts.append(_ESCAPES[escape])
            index += 2
            continue
        parts.append(char)
        index += 1


def tokenize(src: str) -> list[Token]:
    """Split ``src`` into tokens; raise :class:`LexError` with a character offset."""
    tokens: list[Token] = []
    index = 0
    while index < len(src):
        char = src[index]
        if char.isspace():
            index += 1
            continue
        if src.startswith("//", index):
            newline = src.find("\n", index)
            index = len(src) if newline < 0 else newline + 1
            continue
        if char == '"':
            value, end = _read_string(src, index)
            tokens.append(Token("STRING", value, value, index))
            index = end
            continue
        if char.isdigit():
            hit = _FLOAT_RE.match(src, index)
            if hit:
                tokens.append(Token("FLOAT", hit.group(0), float(hit.group(0)), index))
            else:
                hit = _INT_RE.match(src, index)
                tokens.append(Token("INT", hit.group(0), int(hit.group(0)), index))
            after = hit.end()
            # `1.` (digits then a dot not followed by digits) is a LexError.
            if after < len(src) and src[after] == "." and not _FLOAT_RE.match(src, index):
                raise LexError("malformed number", index)
            index = after
            continue
        ident = _IDENT_RE.match(src, index)
        if ident:
            word = ident.group(0)
            kind = "KEYWORD" if word in KEYWORDS else "IDENT"
            tokens.append(Token(kind, word, word, index))
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
