"""Lexer for the microvm language."""

import dataclasses

from .errors import LexError

KEYWORDS: frozenset[str] = frozenset(
    {"let", "print", "if", "else", "while", "true", "false", "and", "or", "not"}
)

# Longest match wins: two-char operators must be listed before their one-char prefix.
OPERATORS: tuple[str, ...] = (
    "==", "!=", "<=", ">=",
    "+", "-", "*", "/", "%", "(", ")", "{", "}", ";", "=", "<", ">",
)


@dataclasses.dataclass(frozen=True)
class Token:
    kind: str
    text: str
    value: object
    offset: int


def _is_ident_start(ch: str) -> bool:
    return ch.isalpha() or ch == "_"


def _is_ident_part(ch: str) -> bool:
    return ch.isalnum() or ch == "_"


def _lex_number(src: str, i: int) -> tuple["Token", int]:
    start = i
    n = len(src)
    while i < n and src[i].isdigit():
        i += 1
    is_float = False
    if i < n and src[i] == ".":
        if i + 1 < n and src[i + 1].isdigit():
            is_float = True
            i += 1
            while i < n and src[i].isdigit():
                i += 1
        else:
            raise LexError("malformed float literal", start)
    if i < n and src[i] in "eE":
        j = i + 1
        if j < n and src[j] in "+-":
            j += 1
        if j < n and src[j].isdigit():
            is_float = True
            i = j
            while i < n and src[i].isdigit():
                i += 1
        else:
            raise LexError("malformed exponent", start)
    text = src[start:i]
    if is_float:
        return Token("FLOAT", text, float(text), start), i
    return Token("INT", text, int(text), start), i


def _lex_string(src: str, i: int) -> tuple["Token", int]:
    start = i
    n = len(src)
    i += 1
    out: list[str] = []
    escapes = {"n": "\n", "t": "\t", '"': '"', "\\": "\\"}
    while True:
        if i >= n:
            raise LexError("unterminated string", start)
        ch = src[i]
        if ch == "\n":
            raise LexError("unterminated string", start)
        if ch == '"':
            i += 1
            break
        if ch == "\\":
            if i + 1 >= n or src[i + 1] not in escapes:
                raise LexError("invalid escape sequence", i)
            out.append(escapes[src[i + 1]])
            i += 2
            continue
        out.append(ch)
        i += 1
    value = "".join(out)
    return Token("STRING", value, value, start), i


def tokenize(src: str) -> list[Token]:
    tokens: list[Token] = []
    i = 0
    n = len(src)
    while i < n:
        ch = src[i]
        if ch in " \t\r\n":
            i += 1
            continue
        if ch == "/" and i + 1 < n and src[i + 1] == "/":
            while i < n and src[i] != "\n":
                i += 1
            continue
        if ch.isdigit():
            tok, i = _lex_number(src, i)
            tokens.append(tok)
            continue
        if ch == '"':
            tok, i = _lex_string(src, i)
            tokens.append(tok)
            continue
        if _is_ident_start(ch):
            start = i
            i += 1
            while i < n and _is_ident_part(src[i]):
                i += 1
            text = src[start:i]
            if text in KEYWORDS:
                tokens.append(Token("KEYWORD", text, text, start))
            else:
                tokens.append(Token("IDENT", text, text, start))
            continue
        matched = None
        for op in OPERATORS:
            if src.startswith(op, i):
                matched = op
                break
        if matched is None:
            raise LexError(f"unexpected character {ch!r}", i)
        tokens.append(Token("OP", matched, matched, i))
        i += len(matched)
    return tokens
