"""Turn minilang source text into a flat list of tokens."""

from __future__ import annotations

import re
from dataclasses import dataclass

from .errors import LexError

KEYWORDS = frozenset({"true", "false", "and", "or", "not"})

_NUMBER_RE = re.compile(r"(?:\d+\.\d+|\.\d+|\d+)(?:[eE][+-]?\d+)?")
_IDENT_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")

_TWO_CHAR_OPS = ("==", "!=", "<=", ">=")
_ONE_CHAR_OPS = frozenset("+-*/%^<>(),")

_STRING_ESCAPES = {"n": "\n", "t": "\t", "r": "\r", '"': '"', "\\": "\\"}


@dataclass(frozen=True)
class Token:
    kind: str          # NUMBER | STRING | IDENT | KEYWORD | OP
    value: object
    position: int


def tokenize(source: str) -> list[Token]:
    """Split `source` into tokens, raising LexError on anything unexpected."""
    tokens: list[Token] = []
    i = 0
    length = len(source)

    while i < length:
        char = source[i]

        if char in " \t\r\n":
            i += 1
            continue

        if char == "#":
            newline = source.find("\n", i)
            i = length if newline == -1 else newline + 1
            continue

        if char == '"':
            value, i = _read_string(source, i)
            tokens.append(Token("STRING", value, i - len(value)))
            continue

        match = _NUMBER_RE.match(source, i)
        if match:
            tokens.append(Token("NUMBER", float(match.group()), i))
            i = match.end()
            continue

        match = _IDENT_RE.match(source, i)
        if match:
            word = match.group()
            kind = "KEYWORD" if word in KEYWORDS else "IDENT"
            tokens.append(Token(kind, word, i))
            i = match.end()
            continue

        if source[i:i + 2] in _TWO_CHAR_OPS:
            tokens.append(Token("OP", source[i:i + 2], i))
            i += 2
            continue

        if char in _ONE_CHAR_OPS:
            tokens.append(Token("OP", char, i))
            i += 1
            continue

        if char == "=":
            raise LexError("unexpected '=' (did you mean '=='?)", i)

        raise LexError(f"unexpected character {char!r}", i)

    return tokens


def _read_string(source: str, start: int) -> tuple[str, int]:
    out: list[str] = []
    i = start + 1
    while True:
        if i >= len(source):
            raise LexError("unterminated string", start)
        char = source[i]
        if char == '"':
            return "".join(out), i + 1
        if char == "\n":
            raise LexError("unterminated string", start)
        if char == "\\":
            if i + 1 >= len(source):
                raise LexError("unterminated string", start)
            escape = source[i + 1]
            if escape not in _STRING_ESCAPES:
                raise LexError(
                    "invalid escape sequence '" + chr(92) + escape + "'", i
                )
            out.append(_STRING_ESCAPES[escape])
            i += 2
            continue
        out.append(char)
        i += 1
