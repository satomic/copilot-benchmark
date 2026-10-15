"""Tokenizer for the MicroVM source language."""

from __future__ import annotations

import dataclasses

from .errors import LexError

KEYWORDS: frozenset[str] = frozenset(
    {"let", "print", "if", "else", "while", "true", "false", "and", "or", "not"}
)
_TWO_CHAR_OPS: frozenset[str] = frozenset({"==", "!=", "<=", ">="})
_ONE_CHAR_OPS: frozenset[str] = frozenset("+-*/%(){};=<>")
_ESCAPES: dict[str, str] = {"n": "\n", "t": "\t", '"': '"', "\\": "\\"}
_DIGITS: str = "0123456789"
_IDENT_START: str = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ_"
_IDENT_BODY: str = _IDENT_START + _DIGITS


@dataclasses.dataclass(frozen=True)
class Token:
    """A lexical token. ``offset`` is the zero-based start position."""

    kind: str
    text: str
    value: object
    offset: int


def tokenize(src: str) -> list[Token]:
    """Split ``src`` into tokens, raising LexError on invalid input."""
    tokens: list[Token] = []
    pos = 0
    while pos < len(src):
        ch = src[pos]
        if ch in " \t\r\n":
            pos += 1
        elif src.startswith("//", pos):
            pos = _skip_comment(src, pos)
        else:
            token, pos = _scan_token(src, pos)
            tokens.append(token)
    return tokens


def _skip_comment(src: str, pos: int) -> int:
    newline = src.find("\n", pos)
    return len(src) if newline < 0 else newline


def _scan_token(src: str, pos: int) -> tuple[Token, int]:
    ch = src[pos]
    if ch in _DIGITS:
        return _scan_number(src, pos)
    if ch in _IDENT_START:
        return _scan_word(src, pos)
    if ch == '"':
        return _scan_string(src, pos)
    pair = src[pos:pos + 2]
    if pair in _TWO_CHAR_OPS:
        return Token("OP", pair, pair, pos), pos + 2
    if ch in _ONE_CHAR_OPS:
        return Token("OP", ch, ch, pos), pos + 1
    raise LexError(f"unexpected character {ch!r}", pos)


def _digits_end(src: str, pos: int) -> int:
    while pos < len(src) and src[pos] in _DIGITS:
        pos += 1
    return pos


def _scan_number(src: str, pos: int) -> tuple[Token, int]:
    end = _digits_end(src, pos)
    is_float = False
    if end < len(src) and src[end] == ".":
        if end + 1 >= len(src) or src[end + 1] not in _DIGITS:
            raise LexError("malformed float literal", pos)
        is_float = True
        end = _digits_end(src, end + 1)
    if is_float and end < len(src) and src[end] in "eE":
        end = _scan_exponent(src, end)
    text = src[pos:end]
    if is_float:
        return Token("FLOAT", text, float(text), pos), end
    try:
        value = int(text)
    except ValueError as exc:
        raise LexError("integer literal too large", pos) from exc
    return Token("INT", text, value, pos), end


def _scan_exponent(src: str, pos: int) -> int:
    """Consume ``e``/``E``, an optional sign and at least one digit."""
    start = pos
    pos += 1
    if pos < len(src) and src[pos] in "+-":
        pos += 1
    if pos >= len(src) or src[pos] not in _DIGITS:
        raise LexError("malformed exponent in float literal", start)
    return _digits_end(src, pos)


def _scan_word(src: str, pos: int) -> tuple[Token, int]:
    end = pos + 1
    while end < len(src) and src[end] in _IDENT_BODY:
        end += 1
    word = src[pos:end]
    kind = "KEYWORD" if word in KEYWORDS else "IDENT"
    return Token(kind, word, word, pos), end


def _scan_string(src: str, pos: int) -> tuple[Token, int]:
    chars: list[str] = []
    index = pos + 1
    while True:
        if index >= len(src):
            raise LexError("unterminated string literal", pos)
        ch = src[index]
        if ch == '"':
            value = "".join(chars)
            return Token("STRING", value, value, pos), index + 1
        if ch == "\n":
            raise LexError("newline inside string literal", index)
        if ch == "\\":
            index = _scan_escape(src, index, pos, chars)
        else:
            chars.append(ch)
            index += 1


def _scan_escape(src: str, index: int, start: int, chars: list[str]) -> int:
    """Decode the escape sequence at ``index`` into ``chars``; return next index."""
    if index + 1 >= len(src):
        raise LexError("unterminated string literal", start)
    escape = src[index + 1]
    if escape not in _ESCAPES:
        raise LexError(f"invalid escape sequence \\{escape}", index)
    chars.append(_ESCAPES[escape])
    return index + 2
