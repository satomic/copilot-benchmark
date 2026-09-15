from __future__ import annotations

from dataclasses import dataclass

from .errors import LexError


@dataclass(frozen=True)
class Token:
    kind: str
    value: object
    offset: int


KEYWORDS = {
    "SELECT": "SELECT",
    "DISTINCT": "DISTINCT",
    "FROM": "FROM",
    "INNER": "INNER",
    "LEFT": "LEFT",
    "JOIN": "JOIN",
    "ON": "ON",
    "WHERE": "WHERE",
    "GROUP": "GROUP",
    "BY": "BY",
    "HAVING": "HAVING",
    "ORDER": "ORDER",
    "ASC": "ASC",
    "DESC": "DESC",
    "LIMIT": "LIMIT",
    "OFFSET": "OFFSET",
    "AS": "AS",
    "AND": "AND",
    "OR": "OR",
    "NOT": "NOT",
    "IS": "IS",
    "NULL": "NULL",
    "TRUE": "TRUE",
    "FALSE": "FALSE",
}


def tokenize(text: str) -> list[Token]:
    tokens: list[Token] = []
    i = 0
    while i < len(text):
        ch = text[i]
        if ch.isspace():
            i += 1
            continue
        if text.startswith("--", i):
            j = text.find("\n", i)
            i = len(text) if j < 0 else j + 1
            continue
        if ch == "'":
            tok, end = _read_string(text, i)
            tokens.append(tok)
            i = end
            continue
        if ch.isdigit() or (ch == "." and i + 1 < len(text) and text[i + 1].isdigit()):
            value, end = _read_number(text, i)
            tokens.append(Token("NUMBER", value, i))
            i = end
            continue
        if ch.isalpha() or ch == "_":
            start = i
            i += 1
            while i < len(text) and (text[i].isalnum() or text[i] == "_"):
                i += 1
            word = text[start:i]
            kind = KEYWORDS.get(word.upper(), "IDENT")
            tokens.append(Token(kind, word, start))
            continue
        op = _read_operator(text, i)
        if op is None:
            raise LexError(i)
        tokens.append(Token(op, op, i))
        i += 1 if len(op) == 1 else 2
    tokens.append(Token("EOF", None, len(text)))
    return tokens


def _read_string(text: str, start: int) -> tuple[Token, int]:
    i = start + 1
    chars: list[str] = []
    while i < len(text):
        ch = text[i]
        if ch == "'":
            if i + 1 < len(text) and text[i + 1] == "'":
                chars.append("'")
                i += 2
                continue
            return Token("TEXT", "".join(chars), start), i + 1
        chars.append(ch)
        i += 1
    raise LexError(start)


def _read_number(text: str, start: int) -> tuple[float | int, int]:
    i = start
    saw_digit = False
    while i < len(text) and text[i].isdigit():
        saw_digit = True
        i += 1
    if i < len(text) and text[i] == ".":
        i += 1
        while i < len(text) and text[i].isdigit():
            saw_digit = True
            i += 1
    if i < len(text) and text[i] in "eE":
        j = i + 1
        if j < len(text) and text[j] in "+-":
            j += 1
        if j < len(text) and text[j].isdigit():
            i = j
            while i < len(text) and text[i].isdigit():
                i += 1
        else:
            raise LexError(start)
    if not saw_digit:
        raise LexError(start)
    raw = text[start:i]
    if "." in raw or "e" in raw.lower():
        return float(raw), i
    return int(raw), i


def _read_operator(text: str, index: int) -> str | None:
    if text.startswith("<>", index):
        return "<>"
    if text.startswith("<=", index):
        return "<="
    if text.startswith(">=", index):
        return ">="
    for op in "=<>+-*/%(),.":
        if text.startswith(op, index):
            return op
    return None
