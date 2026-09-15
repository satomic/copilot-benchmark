"""Lexer for microdb query language."""

from __future__ import annotations

import dataclasses
from microdb.errors import LexError

KEYWORDS = frozenset({
    "SELECT", "DISTINCT", "FROM", "INNER", "LEFT", "JOIN", "ON",
    "WHERE", "GROUP", "BY", "HAVING", "ORDER", "ASC", "DESC",
    "LIMIT", "OFFSET", "AS", "AND", "OR", "NOT", "IS", "NULL",
    "TRUE", "FALSE"
})


@dataclasses.dataclass(frozen=True)
class Token:
    """Lexical token with source offset."""

    kind: str
    value: object
    offset: int


def _lex_string(query: str, start: int) -> tuple[Token, int]:
    idx = start + 1
    chars: list[str] = []
    n = len(query)
    while idx < n:
        ch = query[idx]
        if ch == "'":
            if idx + 1 < n and query[idx + 1] == "'":
                chars.append("'")
                idx += 2
            else:
                return Token("TEXT", "".join(chars), start), idx + 1
        else:
            chars.append(ch)
            idx += 1
    raise LexError("Unterminated string literal", start)


def _lex_exponent(query: str, idx: int, start: int) -> int:
    n = len(query)
    if idx < n and query[idx] in "eE":
        exp_start = idx
        idx += 1
        if idx < n and query[idx] in "+-":
            idx += 1
        digit_start = idx
        while idx < n and query[idx].isdigit():
            idx += 1
        if idx == digit_start:
            raise LexError("Malformed float exponent", exp_start)
    return idx


def _lex_number(query: str, start: int) -> tuple[Token, int]:
    idx = start
    n = len(query)
    is_float = False
    if query[idx] == ".":
        is_float = True
        idx += 1
        while idx < n and query[idx].isdigit():
            idx += 1
    else:
        while idx < n and query[idx].isdigit():
            idx += 1
        if idx < n and query[idx] == ".":
            is_float = True
            idx += 1
            while idx < n and query[idx].isdigit():
                idx += 1
    exp_idx = _lex_exponent(query, idx, start)
    if exp_idx != idx:
        is_float = True
        idx = exp_idx
    raw = query[start:idx]
    val: object = float(raw) if is_float else int(raw)
    kind = "FLOAT" if is_float else "INT"
    return Token(kind, val, start), idx


def _lex_ident_or_keyword(query: str, start: int) -> tuple[Token, int]:
    idx = start
    n = len(query)
    while idx < n and (query[idx].isalnum() or query[idx] == "_"):
        idx += 1
    text = query[start:idx]
    upper = text.upper()
    if upper in KEYWORDS:
        if upper == "TRUE":
            return Token("BOOL", True, start), idx
        if upper == "FALSE":
            return Token("BOOL", False, start), idx
        if upper == "NULL":
            return Token("NULL", None, start), idx
        return Token("KEYWORD", upper, start), idx
    return Token("IDENT", text, start), idx


def _lex_operator(query: str, start: int) -> tuple[Token, int]:
    n = len(query)
    two = query[start : start + 2]
    if two in ("<>", "<=", ">="):
        return Token("OP", two, start), start + 2
    ch = query[start]
    if ch in "=<>+-*/%(),.":
        return Token("OP", ch, start), start + 1
    raise LexError(f"Unexpected character: {ch!r}", start)


def lex(query: str) -> list[Token]:
    """Tokenize query string into a list of Tokens."""
    tokens: list[Token] = []
    idx = 0
    n = len(query)
    while idx < n:
        ch = query[idx]
        if ch.isspace():
            idx += 1
        elif ch == "-" and idx + 1 < n and query[idx + 1] == "-":
            idx += 2
            while idx < n and query[idx] != "\n":
                idx += 1
        elif ch == "'":
            tok, idx = _lex_string(query, idx)
            tokens.append(tok)
        elif ch.isdigit() or (ch == "." and idx + 1 < n and query[idx + 1].isdigit()):
            tok, idx = _lex_number(query, idx)
            tokens.append(tok)
        elif ch.isalpha() or ch == "_":
            tok, idx = _lex_ident_or_keyword(query, idx)
            tokens.append(tok)
        else:
            tok, idx = _lex_operator(query, idx)
            tokens.append(tok)
    tokens.append(Token("EOF", "", n))
    return tokens
