"""Tokenizer for the microvm language."""

from __future__ import annotations

import dataclasses
import re

from .errors import LexError

KEYWORDS: frozenset[str] = frozenset(
    {"let", "print", "if", "else", "while", "true", "false", "and", "or", "not"}
)

# Longest operators first so that the alternation prefers "==" over "=".
_OPERATORS: tuple[str, ...] = (
    "==", "!=", "<=", ">=", "+", "-", "*", "/", "%", "(", ")", "{", "}", ";", "=", "<", ">",
)
_OP_RE = re.compile("|".join(re.escape(op) for op in _OPERATORS))
_IDENT_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
# Floats are digits "." digits with an optional exponent; a bare exponent (1e3) or a
# dangling dot (1. / .5) is rejected by the number branch below.
_NUMBER_RE = re.compile(r"[0-9]+(\.[0-9]+([eE][+-]?[0-9]+)?)?")
_ESCAPES: dict[str, str] = {"n": "\n", "t": "\t", '"': '"', "\\": "\\"}


@dataclasses.dataclass(frozen=True)
class Token:
    kind: str
    text: str
    value: object
    offset: int


def _lex_number(src: str, pos: int) -> Token:
    match = _NUMBER_RE.match(src, pos)
    assert match is not None
    end = match.end()
    if end < len(src) and (src[end] == "." or src[end].isalpha() or src[end] == "_"):
        raise LexError("malformed number", pos)
    text = match.group(0)
    if match.group(1) is None:
        return Token("INT", text, int(text), pos)
    return Token("FLOAT", text, float(text), pos)


def _lex_string(src: str, pos: int) -> tuple[Token, int]:
    chars: list[str] = []
    i = pos + 1
    while True:
        if i >= len(src):
            raise LexError("unterminated string", pos)
        ch = src[i]
        if ch == '"':
            value = "".join(chars)
            return Token("STRING", value, value, pos), i + 1
        if ch == "\n":
            raise LexError("newline inside string", i)
        if ch == "\\":
            if i + 1 >= len(src):
                raise LexError("unterminated string", pos)
            esc = src[i + 1]
            if esc not in _ESCAPES:
                raise LexError(f"invalid escape sequence \\{esc}", i)
            chars.append(_ESCAPES[esc])
            i += 2
            continue
        chars.append(ch)
        i += 1


def tokenize(src: str) -> list[Token]:
    tokens: list[Token] = []
    pos = 0
    length = len(src)
    while pos < length:
        ch = src[pos]
        if ch.isspace():
            pos += 1
        elif src.startswith("//", pos):
            newline = src.find("\n", pos)
            pos = length if newline < 0 else newline + 1
        elif "0" <= ch <= "9":
            token = _lex_number(src, pos)
            tokens.append(token)
            pos += len(token.text)
        elif ch == '"':
            token, pos = _lex_string(src, pos)
            tokens.append(token)
        elif ch == "_" or "A" <= ch <= "Z" or "a" <= ch <= "z":
            match = _IDENT_RE.match(src, pos)
            assert match is not None
            text = match.group(0)
            kind = "KEYWORD" if text in KEYWORDS else "IDENT"
            tokens.append(Token(kind, text, text, pos))
            pos = match.end()
        else:
            match = _OP_RE.match(src, pos)
            if match is None:
                raise LexError(f"unexpected character {ch!r}", pos)
            text = match.group(0)
            tokens.append(Token("OP", text, text, pos))
            pos = match.end()
    return tokens
