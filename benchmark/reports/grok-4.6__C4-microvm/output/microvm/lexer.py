from __future__ import annotations

import dataclasses

from microvm.errors import LexError

KEYWORDS: frozenset[str] = frozenset(
    {
        "let",
        "print",
        "if",
        "else",
        "while",
        "true",
        "false",
        "and",
        "or",
        "not",
    }
)
_TWO_CHAR_OPS: frozenset[str] = frozenset({"==", "!=", "<=", ">="})
_ONE_CHAR_OPS: frozenset[str] = frozenset(list("+-*/%(){};=<>"))
_ESCAPES: dict[str, str] = {"n": "\n", "t": "\t", '"': '"', "\\": "\\"}


@dataclasses.dataclass(frozen=True)
class Token:
    kind: str
    text: str
    value: object
    offset: int


def tokenize(src: str) -> list[Token]:
    tokens: list[Token] = []
    i = 0
    n = len(src)
    while i < n:
        ch = src[i]
        if ch in " \t\n\r":
            i += 1
            continue
        if ch == "/" and i + 1 < n and src[i + 1] == "/":
            i = src.find("\n", i + 2)
            i = n if i < 0 else i
            continue
        nxt, i = _next_token(src, i, n)
        tokens.append(nxt)
    return tokens


def _next_token(src: str, i: int, n: int) -> tuple[Token, int]:
    ch = src[i]
    if ch == '"':
        return _read_string(src, i, n)
    if ch.isdigit():
        return _read_number(src, i, n)
    if ch.isalpha() or ch == "_":
        return _read_ident(src, i, n)
    two = src[i : i + 2]
    if two in _TWO_CHAR_OPS:
        return Token("OP", two, two, i), i + 2
    if ch in _ONE_CHAR_OPS:
        return Token("OP", ch, ch, i), i + 1
    raise LexError(f"unexpected character {ch!r}", i)


def _read_ident(src: str, i: int, n: int) -> tuple[Token, int]:
    start = i
    i += 1
    while i < n and (src[i].isalnum() or src[i] == "_"):
        i += 1
    text = src[start:i]
    kind = "KEYWORD" if text in KEYWORDS else "IDENT"
    return Token(kind, text, text, start), i


def _read_number(src: str, i: int, n: int) -> tuple[Token, int]:
    start = i
    while i < n and src[i].isdigit():
        i += 1
    if i < n and src[i] == ".":
        return _read_float(src, start, i, n)
    text = src[start:i]
    return Token("INT", text, int(text), start), i


def _read_float(src: str, start: int, i: int, n: int) -> tuple[Token, int]:
    if i + 1 >= n or not src[i + 1].isdigit():
        raise LexError("float requires digits on both sides of the dot", start)
    i += 1
    while i < n and src[i].isdigit():
        i += 1
    if i < n and src[i] in "eE":
        i = _consume_exponent(src, start, i, n)
    text = src[start:i]
    return Token("FLOAT", text, float(text), start), i


def _consume_exponent(src: str, start: int, i: int, n: int) -> int:
    i += 1
    if i < n and src[i] in "+-":
        i += 1
    if i >= n or not src[i].isdigit():
        raise LexError("invalid float exponent", start)
    while i < n and src[i].isdigit():
        i += 1
    return i


def _read_string(src: str, i: int, n: int) -> tuple[Token, int]:
    start = i
    i += 1
    chars: list[str] = []
    while i < n:
        ch = src[i]
        if ch == "\n":
            raise LexError("newline in string", i)
        if ch == '"':
            decoded = "".join(chars)
            return Token("STRING", decoded, decoded, start), i + 1
        if ch == "\\":
            chars.append(_unescape(src, i, n, start))
            i += 2
            continue
        chars.append(ch)
        i += 1
    raise LexError("unterminated string", start)


def _unescape(src: str, i: int, n: int, start: int) -> str:
    if i + 1 >= n:
        raise LexError("unterminated string", start)
    nxt = src[i + 1]
    if nxt not in _ESCAPES:
        raise LexError("invalid escape sequence", i)
    return _ESCAPES[nxt]
