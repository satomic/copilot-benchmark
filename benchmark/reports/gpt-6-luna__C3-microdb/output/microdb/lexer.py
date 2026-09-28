from __future__ import annotations

from dataclasses import dataclass

from .errors import LexError


KEYWORDS = {
    "SELECT", "DISTINCT", "FROM", "INNER", "LEFT", "JOIN", "ON", "WHERE",
    "GROUP", "BY", "HAVING", "ORDER", "ASC", "DESC", "LIMIT", "OFFSET",
    "AS", "AND", "OR", "NOT", "IS", "NULL", "TRUE", "FALSE",
}


@dataclass(frozen=True)
class Token:
    kind: str
    value: str
    offset: int
    end: int


def tokenize(source: str) -> list[Token]:
    tokens: list[Token] = []
    i = 0
    while i < len(source):
        ch = source[i]
        if ch.isspace():
            i += 1
            continue
        if source.startswith("--", i):
            newline = source.find("\n", i + 2)
            i = len(source) if newline < 0 else newline + 1
            continue
        if ch == "'":
            start = i
            i += 1
            value: list[str] = []
            while i < len(source):
                if source[i] == "'":
                    if i + 1 < len(source) and source[i + 1] == "'":
                        value.append("'")
                        i += 2
                        continue
                    i += 1
                    break
                value.append(source[i])
                i += 1
            else:
                raise LexError("unterminated text literal", start)
            tokens.append(Token("TEXT", "".join(value), start, i))
            continue
        if _digit(ch) or (ch == "." and i + 1 < len(source) and _digit(source[i + 1])):
            token, i = _number(source, i)
            tokens.append(token)
            continue
        if _identifier_start(ch):
            start = i
            i += 1
            while i < len(source) and _identifier_continue(source[i]):
                i += 1
            value = source[start:i]
            upper = value.upper()
            tokens.append(Token(upper if upper in KEYWORDS else "IDENT", value, start, i))
            continue
        if source.startswith(("<>", "<=", ">="), i):
            tokens.append(Token("OP", source[i:i + 2], i, i + 2))
            i += 2
            continue
        if ch in "=<>+-*/%(),.":
            kind = "OP" if ch in "=<>+-*/%" else ch
            tokens.append(Token(kind, ch, i, i + 1))
            i += 1
            continue
        raise LexError(f"unexpected character {ch!r}", i)
    tokens.append(Token("EOF", "", len(source), len(source)))
    return tokens


def _number(source: str, start: int) -> tuple[Token, int]:
    i = start
    before = 0
    while i < len(source) and _digit(source[i]):
        i += 1
        before += 1
    floating = False
    if i < len(source) and source[i] == ".":
        floating = True
        i += 1
        while i < len(source) and _digit(source[i]):
            i += 1
    elif before == 0:
        floating = True
        while i < len(source) and _digit(source[i]):
            i += 1
    if i < len(source) and source[i] in "eE":
        floating = True
        exponent = i
        i += 1
        if i < len(source) and source[i] in "+-":
            i += 1
        digits = i
        while i < len(source) and _digit(source[i]):
            i += 1
        if i == digits:
            raise LexError("malformed exponent", exponent)
    value = source[start:i]
    kind = "FLOAT" if floating else "INT"
    try:
        parsed = float(value) if floating else int(value)
    except ValueError as exc:
        raise LexError("malformed number", start) from exc
    return Token(kind, str(parsed), start, i), i


def _digit(char: str) -> bool:
    return "0" <= char <= "9"


def _identifier_start(char: str) -> bool:
    return char == "_" or "A" <= char <= "Z" or "a" <= char <= "z"


def _identifier_continue(char: str) -> bool:
    return _identifier_start(char) or _digit(char)
