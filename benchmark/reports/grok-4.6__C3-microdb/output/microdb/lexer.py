"""Tokenizer for the microdb query language."""

from __future__ import annotations

import dataclasses

from microdb.errors import LexError

KEYWORDS = frozenset(
    {
        "SELECT",
        "DISTINCT",
        "FROM",
        "INNER",
        "LEFT",
        "JOIN",
        "ON",
        "WHERE",
        "GROUP",
        "BY",
        "HAVING",
        "ORDER",
        "ASC",
        "DESC",
        "LIMIT",
        "OFFSET",
        "AS",
        "AND",
        "OR",
        "NOT",
        "IS",
        "NULL",
        "TRUE",
        "FALSE",
    }
)

_TWO = {"<>": "<>", "<=": "<=", ">=": ">="}
_ONE = frozenset("=<>+-*/%(),.")


@dataclasses.dataclass(frozen=True)
class Token:
    kind: str
    value: object
    offset: int
    text: str


def tokenize(source: str) -> list[Token]:
    tokens: list[Token] = []
    i = 0
    n = len(source)
    while i < n:
        ch = source[i]
        if ch in " \t\r\n":
            i += 1
            continue
        if ch == "-" and i + 1 < n and source[i + 1] == "-":
            i = _skip_comment(source, i)
            continue
        if ch == "'":
            tok, i = _scan_string(source, i)
            tokens.append(tok)
            continue
        if ch.isdigit() or (ch == "." and i + 1 < n and source[i + 1].isdigit()):
            tok, i = _scan_number(source, i)
            tokens.append(tok)
            continue
        if ch.isalpha() or ch == "_":
            tok, i = _scan_ident(source, i)
            tokens.append(tok)
            continue
        two = source[i : i + 2]
        if two in _TWO:
            tokens.append(Token(_TWO[two], _TWO[two], i, two))
            i += 2
            continue
        if ch in _ONE:
            tokens.append(Token(ch, ch, i, ch))
            i += 1
            continue
        raise LexError(f"unexpected character {ch!r}", i)
    tokens.append(Token("EOF", None, n, ""))
    return tokens


def _skip_comment(source: str, i: int) -> int:
    n = len(source)
    i += 2
    while i < n and source[i] not in "\n\r":
        i += 1
    return i


def _scan_string(source: str, start: int) -> tuple[Token, int]:
    i = start + 1
    n = len(source)
    parts: list[str] = []
    while i < n:
        ch = source[i]
        if ch == "'":
            if i + 1 < n and source[i + 1] == "'":
                parts.append("'")
                i += 2
                continue
            text = source[start : i + 1]
            return Token("TEXT", "".join(parts), start, text), i + 1
        parts.append(ch)
        i += 1
    raise LexError("unterminated text literal", start)


def _scan_ident(source: str, start: int) -> tuple[Token, int]:
    i = start + 1
    n = len(source)
    while i < n and (source[i].isalnum() or source[i] == "_"):
        i += 1
    text = source[start:i]
    upper = text.upper()
    if upper in KEYWORDS:
        value: object = True if upper == "TRUE" else False if upper == "FALSE" else None
        return Token(upper, value, start, text), i
    return Token("IDENT", text, start, text), i


def _scan_number(source: str, start: int) -> tuple[Token, int]:
    i = start
    n = len(source)
    is_float = False
    if source[i] == ".":
        is_float = True
        i = _digits(source, i + 1)
    else:
        i = _digits(source, i)
        if i < n and source[i] == ".":
            is_float = True
            i = _digits(source, i + 1)
    i, exp_float = _scan_exponent(source, i)
    is_float = is_float or exp_float
    text = source[start:i]
    if is_float:
        return Token("FLOAT", float(text), start, text), i
    return Token("INT", int(text), start, text), i


def _digits(source: str, i: int) -> int:
    n = len(source)
    while i < n and source[i].isdigit():
        i += 1
    return i


def _scan_exponent(source: str, i: int) -> tuple[int, bool]:
    n = len(source)
    if i >= n or source[i] not in "eE":
        return i, False
    j = i + 1
    if j < n and source[j] in "+-":
        j += 1
    if j < n and source[j].isdigit():
        return _digits(source, j), True
    return i, False
