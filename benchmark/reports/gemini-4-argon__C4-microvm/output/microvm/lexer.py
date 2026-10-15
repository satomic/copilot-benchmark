from __future__ import annotations

import dataclasses
from microvm.errors import LexError


@dataclasses.dataclass(frozen=True)
class Token:
    kind: str      # "INT" | "FLOAT" | "STRING" | "IDENT" | "KEYWORD" | "OP"
    text: str      # the source lexeme (for STRING: the decoded value)
    value: object  # INT -> int, FLOAT -> float, STRING -> decoded str, else same as text
    offset: int    # zero-based character offset of the first character


KEYWORDS: frozenset[str] = frozenset(
    {"let", "print", "if", "else", "while", "true", "false", "and", "or", "not"}
)

TWO_CHAR_OPS: frozenset[str] = frozenset({"==", "!=", "<=", ">="})
ONE_CHAR_OPS: frozenset[str] = frozenset(
    {"+", "-", "*", "/", "%", "(", ")", "{", "}", ";", "=", "<", ">"}
)

ESCAPES: dict[str, str] = {
    "n": "\n",
    "t": "\t",
    '"': '"',
    "\\": "\\",
}


def _lex_string(src: str, start: int) -> tuple[Token, int]:
    n = len(src)
    i = start + 1
    chars: list[str] = []
    while i < n:
        ch = src[i]
        if ch == '"':
            decoded = "".join(chars)
            return Token("STRING", decoded, decoded, start), i + 1
        if ch in ("\n", "\r"):
            raise LexError("Newline in string literal", start)
        if ch == "\\":
            if i + 1 >= n:
                raise LexError("Unterminated string escape", start)
            esc = src[i + 1]
            if esc not in ESCAPES:
                raise LexError(f"Invalid escape sequence '\\{esc}'", start)
            chars.append(ESCAPES[esc])
            i += 2
        else:
            chars.append(ch)
            i += 1
    raise LexError("Unterminated string literal", start)


def _lex_number(src: str, start: int) -> tuple[Token, int]:
    n = len(src)
    i = start
    while i < n and src[i].isdigit():
        i += 1
    is_float = False
    if i < n and src[i] == ".":
        is_float = True
        i += 1
        if i >= n or not src[i].isdigit():
            raise LexError("Malformed float literal: missing fractional digits", start)
        while i < n and src[i].isdigit():
            i += 1
        if i < n and src[i] in ("e", "E"):
            i += 1
            if i < n and src[i] in ("+", "-"):
                i += 1
            if i >= n or not src[i].isdigit():
                raise LexError("Malformed float exponent", start)
            while i < n and src[i].isdigit():
                i += 1
    if i < n and (src[i].isalpha() or src[i] == "_" or src[i] == "."):
        raise LexError(f"Malformed number literal at {src[i]!r}", start)
    text = src[start:i]
    if is_float:
        return Token("FLOAT", text, float(text), start), i
    return Token("INT", text, int(text), start), i


def _lex_ident(src: str, start: int) -> tuple[Token, int]:
    n = len(src)
    i = start
    while i < n and (src[i].isalnum() or src[i] == "_"):
        i += 1
    text = src[start:i]
    kind = "KEYWORD" if text in KEYWORDS else "IDENT"
    return Token(kind, text, text, start), i


def tokenize(src: str) -> list[Token]:
    tokens: list[Token] = []
    n = len(src)
    i = 0
    while i < n:
        ch = src[i]
        if ch.isspace():
            i += 1
        elif src.startswith("//", i):
            i += 2
            while i < n and src[i] != "\n":
                i += 1
        elif ch == '"':
            tok, i = _lex_string(src, i)
            tokens.append(tok)
        elif ch.isdigit():
            tok, i = _lex_number(src, i)
            tokens.append(tok)
        elif ch.isalpha() or ch == "_":
            tok, i = _lex_ident(src, i)
            tokens.append(tok)
        elif src[i : i + 2] in TWO_CHAR_OPS:
            op = src[i : i + 2]
            tokens.append(Token("OP", op, op, i))
            i += 2
        elif ch in ONE_CHAR_OPS:
            tokens.append(Token("OP", ch, ch, i))
            i += 1
        else:
            raise LexError(f"Unexpected character {ch!r}", i)
    return tokens
