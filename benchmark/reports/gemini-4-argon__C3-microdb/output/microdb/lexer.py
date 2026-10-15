from __future__ import annotations

import dataclasses

from microdb.errors import LexError

KEYWORDS: frozenset[str] = frozenset(
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

TWO_CHAR_OPS: frozenset[str] = frozenset({"<>", "<=", ">="})
ONE_CHAR_OPS: frozenset[str] = frozenset(
    {"=", "<", ">", "+", "-", "*", "/", "%", "(", ")", ",", "."}
)


@dataclasses.dataclass(frozen=True)
class Token:
    kind: str
    value: object
    text: str
    offset: int
    end: int


def _lex_string(source: str, start: int) -> Token:
    n = len(source)
    i = start + 1
    chars: list[str] = []
    while i < n:
        ch = source[i]
        if ch == "'":
            if i + 1 < n and source[i + 1] == "'":
                chars.append("'")
                i += 2
                continue
            return Token("TEXT", "".join(chars), source[start : i + 1], start, i + 1)
        chars.append(ch)
        i += 1
    raise LexError("Unterminated text literal", offset=start)


def _lex_number(source: str, start: int) -> Token:
    n = len(source)
    i = start
    is_float = False
    while i < n and source[i].isdigit():
        i += 1
    if i < n and source[i] == ".":
        is_float = True
        i += 1
        while i < n and source[i].isdigit():
            i += 1
    if i < n and source[i] in ("e", "E"):
        is_float = True
        i += 1
        if i < n and source[i] in ("+", "-"):
            i += 1
        exp_start = i
        while i < n and source[i].isdigit():
            i += 1
        if i == exp_start:
            raise LexError("Invalid exponent in float literal", offset=start)
    raw = source[start:i]
    val: object = float(raw) if is_float else int(raw)
    kind = "FLOAT" if is_float else "INT"
    return Token(kind, val, raw, start, i)


def _lex_word(source: str, start: int) -> Token:
    n = len(source)
    i = start + 1
    while i < n and (source[i].isalnum() or source[i] == "_"):
        i += 1
    raw = source[start:i]
    upper = raw.upper()
    if upper in KEYWORDS:
        return Token("KEYWORD", upper, raw, start, i)
    return Token("IDENT", raw, raw, start, i)


def tokenize(source: str) -> list[Token]:
    tokens: list[Token] = []
    n = len(source)
    i = 0
    while i < n:
        ch = source[i]
        if ch.isspace():
            i += 1
        elif source[i : i + 2] == "--":
            i += 2
            while i < n and source[i] != "\n":
                i += 1
        elif ch == "'":
            tok = _lex_string(source, i)
            tokens.append(tok)
            i = tok.end
        elif ch.isdigit() or (ch == "." and i + 1 < n and source[i + 1].isdigit()):
            tok = _lex_number(source, i)
            tokens.append(tok)
            i = tok.end
        elif ch.isalpha() or ch == "_":
            tok = _lex_word(source, i)
            tokens.append(tok)
            i = tok.end
        elif source[i : i + 2] in TWO_CHAR_OPS:
            op = source[i : i + 2]
            tokens.append(Token("OP", op, op, i, i + 2))
            i += 2
        elif ch in ONE_CHAR_OPS:
            tokens.append(Token("OP", ch, ch, i, i + 1))
            i += 1
        else:
            raise LexError(f"Unexpected character {ch!r}", offset=i)
    return tokens
