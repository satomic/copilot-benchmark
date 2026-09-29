"""Tokenizer for the microvm language."""

from __future__ import annotations

import dataclasses
import re

from .errors import LexError

KEYWORDS: frozenset[str] = frozenset(
    {"let", "print", "if", "else", "while", "true", "false", "and", "or", "not"}
)
_TWO_CHAR_OPS = ("==", "!=", "<=", ">=")
_ONE_CHAR_OPS = frozenset("+-*/%(){};=<>")
_ESCAPES = {"n": "\n", "t": "\t", '"': '"', "\\": "\\"}
_NUMBER = re.compile(r"[0-9]+(?:\.[0-9]+(?:[eE][+-]?[0-9]+)?)?")
_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_DIGITS = frozenset("0123456789")
_IDENT_CHARS = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_")


@dataclasses.dataclass(frozen=True)
class Token:
    kind: str
    text: str
    value: object
    offset: int


def _lex_number(src: str, pos: int) -> Token:
    match = _NUMBER.match(src, pos)
    assert match is not None
    end = match.end()
    if end < len(src) and (src[end] == "." or src[end] in _IDENT_CHARS):
        # "1.", "1.5.", "1.5e", "12abc": reported at the start of the literal.
        raise LexError("malformed number literal", pos)
    text = match.group(0)
    if "." in text:
        return Token("FLOAT", text, float(text), pos)
    return Token("INT", text, int(text), pos)


def _lex_string(src: str, pos: int) -> tuple[Token, int]:
    chars: list[str] = []
    i = pos + 1
    while i < len(src):
        ch = src[i]
        if ch == '"':
            value = "".join(chars)
            return Token("STRING", value, value, pos), i + 1
        if ch == "\n":
            raise LexError("newline inside string literal", i)
        if ch == "\\":
            if i + 1 >= len(src):
                break
            escaped = _ESCAPES.get(src[i + 1])
            if escaped is None:
                raise LexError("invalid escape sequence", i)
            chars.append(escaped)
            i += 2
            continue
        chars.append(ch)
        i += 1
    raise LexError("unterminated string literal", pos)


def _lex_operator(src: str, pos: int) -> Token:
    two = src[pos:pos + 2]
    if two in _TWO_CHAR_OPS:
        return Token("OP", two, two, pos)
    if src[pos] in _ONE_CHAR_OPS:
        return Token("OP", src[pos], src[pos], pos)
    raise LexError(f"unexpected character {src[pos]!r}", pos)


def tokenize(src: str) -> list[Token]:
    """Split ``src`` into tokens; no end-of-input token is emitted."""
    if not isinstance(src, str):
        raise TypeError("source must be a str")
    tokens: list[Token] = []
    pos = 0
    length = len(src)
    while pos < length:
        ch = src[pos]
        if ch.isspace():
            pos += 1
        elif src.startswith("//", pos):
            newline = src.find("\n", pos)
            pos = length if newline < 0 else newline
        elif ch in _DIGITS:
            token = _lex_number(src, pos)
            tokens.append(token)
            pos += len(token.text)
        elif ch == '"':
            token, pos = _lex_string(src, pos)
            tokens.append(token)
        elif ch in _IDENT_CHARS:
            match = _IDENT.match(src, pos)
            assert match is not None
            word = match.group(0)
            kind = "KEYWORD" if word in KEYWORDS else "IDENT"
            tokens.append(Token(kind, word, word, pos))
            pos = match.end()
        else:
            token = _lex_operator(src, pos)
            tokens.append(token)
            pos += len(token.text)
    return tokens
