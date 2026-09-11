"""Lexer: tokenize a microdb query string."""

from __future__ import annotations

import dataclasses

from microdb.errors import LexError

KEYWORDS = {
    "SELECT", "DISTINCT", "FROM", "INNER", "LEFT", "JOIN", "ON", "WHERE",
    "GROUP", "BY", "HAVING", "ORDER", "ASC", "DESC", "LIMIT", "OFFSET",
    "AS", "AND", "OR", "NOT", "IS", "NULL", "TRUE", "FALSE",
}

_MULTI_OPS = ("<>", "<=", ">=")
_SINGLE_OPS = "=<>+-*/%(),."


@dataclasses.dataclass(frozen=True)
class Token:
    kind: str  # "KEYWORD" | "IDENT" | "INT" | "FLOAT" | "TEXT" | "OP" | "EOF"
    value: object
    start: int
    end: int


def _is_ident_start(ch: str) -> bool:
    return ch.isalpha() or ch == "_"


def _is_ident_part(ch: str) -> bool:
    return ch.isalnum() or ch == "_"


def _read_text_literal(src: str, i: int) -> tuple[str, int]:
    start = i
    i += 1
    parts: list[str] = []
    while True:
        if i >= len(src):
            raise LexError("unterminated text literal", start)
        ch = src[i]
        if ch == "'":
            if i + 1 < len(src) and src[i + 1] == "'":
                parts.append("'")
                i += 2
                continue
            i += 1
            break
        parts.append(ch)
        i += 1
    return "".join(parts), i


def _read_number(src: str, i: int) -> tuple[Token, int]:
    start = i
    is_float = False
    while i < len(src) and src[i].isdigit():
        i += 1
    if i < len(src) and src[i] == ".":
        is_float = True
        i += 1
        while i < len(src) and src[i].isdigit():
            i += 1
    if i < len(src) and src[i] in "eE":
        save = i
        j = i + 1
        if j < len(src) and src[j] in "+-":
            j += 1
        if j < len(src) and src[j].isdigit():
            is_float = True
            j += 1
            while j < len(src) and src[j].isdigit():
                j += 1
            i = j
        else:
            i = save
    text = src[start:i]
    if is_float:
        return Token("FLOAT", float(text), start, i), i
    return Token("INT", int(text), start, i), i


def tokenize(src: str) -> list[Token]:
    """Tokenize src into a list of Tokens, terminated by an EOF token."""
    tokens: list[Token] = []
    i = 0
    n = len(src)
    while i < n:
        ch = src[i]
        if ch in " \t\r\n":
            i += 1
            continue
        if ch == "-" and i + 1 < n and src[i + 1] == "-":
            while i < n and src[i] != "\n":
                i += 1
            continue
        if ch == "'":
            text, new_i = _read_text_literal(src, i)
            tokens.append(Token("TEXT", text, i, new_i))
            i = new_i
            continue
        if ch.isdigit() or (ch == "." and i + 1 < n and src[i + 1].isdigit()):
            tok, new_i = _read_number(src, i)
            tokens.append(tok)
            i = new_i
            continue
        if _is_ident_start(ch):
            start = i
            i += 1
            while i < n and _is_ident_part(src[i]):
                i += 1
            text = src[start:i]
            upper = text.upper()
            if upper in KEYWORDS:
                tokens.append(Token("KEYWORD", upper, start, i))
            else:
                tokens.append(Token("IDENT", text, start, i))
            continue
        matched = False
        for op in _MULTI_OPS:
            if src.startswith(op, i):
                tokens.append(Token("OP", op, i, i + len(op)))
                i += len(op)
                matched = True
                break
        if matched:
            continue
        if ch in _SINGLE_OPS:
            tokens.append(Token("OP", ch, i, i + 1))
            i += 1
            continue
        raise LexError(f"unexpected character {ch!r}", i)
    tokens.append(Token("EOF", None, n, n))
    return tokens
