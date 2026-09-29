from dataclasses import dataclass

from .errors import LexError

KEYWORDS = {
    "SELECT", "DISTINCT", "FROM", "INNER", "LEFT", "JOIN", "ON", "WHERE",
    "GROUP", "BY", "HAVING", "ORDER", "ASC", "DESC", "LIMIT", "OFFSET",
    "AS", "AND", "OR", "NOT", "IS", "NULL", "TRUE", "FALSE",
}
TWO_CHAR = {"<>", "<=", ">="}
ONE_CHAR = set("=<>+-*/%(),.")


def _digit(character: str) -> bool:
    return "0" <= character <= "9"


def _letter(character: str) -> bool:
    return "A" <= character <= "Z" or "a" <= character <= "z"


@dataclass(frozen=True)
class Token:
    kind: str
    value: object
    start: int
    end: int


def _number(text: str, start: int) -> tuple[Token, int]:
    i, size = start, len(text)
    while i < size and _digit(text[i]):
        i += 1
    is_float = False
    if i < size and text[i] == ".":
        is_float = True
        i += 1
        while i < size and _digit(text[i]):
            i += 1
    if i < size and text[i] in "eE":
        is_float = True
        exp = i
        i += 1
        if i < size and text[i] in "+-":
            i += 1
        digits = i
        while i < size and _digit(text[i]):
            i += 1
        if digits == i:
            raise LexError("invalid numeric exponent", exp)
    raw = text[start:i]
    value: object = float(raw) if is_float else int(raw)
    return Token("FLOAT" if is_float else "INT", value, start, i), i


def _string(text: str, start: int) -> tuple[Token, int]:
    i, pieces = start + 1, []
    while i < len(text):
        if text[i] != "'":
            pieces.append(text[i])
            i += 1
        elif i + 1 < len(text) and text[i + 1] == "'":
            pieces.append("'")
            i += 2
        else:
            return Token("TEXT", "".join(pieces), start, i + 1), i + 1
    raise LexError("unterminated text literal", start)


def tokenize(text: str) -> list[Token]:
    tokens: list[Token] = []
    i = 0
    while i < len(text):
        if text[i].isspace():
            i += 1
        elif text.startswith("--", i):
            newline = text.find("\n", i + 2)
            i = len(text) if newline < 0 else newline + 1
        elif text[i] == "'":
            token, i = _string(text, i)
            tokens.append(token)
        elif _digit(text[i]) or (
            text[i] == "." and i + 1 < len(text) and _digit(text[i + 1])
        ):
            token, i = _number(text, i)
            tokens.append(token)
        elif _letter(text[i]) or text[i] == "_":
            start = i
            i += 1
            while i < len(text) and (
                _letter(text[i]) or _digit(text[i]) or text[i] == "_"
            ):
                i += 1
            raw = text[start:i]
            upper = raw.upper()
            tokens.append(Token(upper if upper in KEYWORDS else "IDENT", raw, start, i))
        elif text[i:i + 2] in TWO_CHAR:
            tokens.append(Token(text[i:i + 2], text[i:i + 2], i, i + 2))
            i += 2
        elif text[i] in ONE_CHAR:
            tokens.append(Token(text[i], text[i], i, i + 1))
            i += 1
        else:
            raise LexError(f"unexpected character {text[i]!r}", i)
    tokens.append(Token("EOF", None, len(text), len(text)))
    return tokens
