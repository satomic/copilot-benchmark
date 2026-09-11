"""Hand written lexer for the micro language."""

from __future__ import annotations

import dataclasses

from .errors import LexError

KEYWORDS: frozenset[str] = frozenset(
    {"let", "print", "if", "else", "while", "true", "false", "and", "or", "not"}
)

# Longest match wins, so two character operators are tried first.
_OPERATORS: tuple[str, ...] = (
    "==",
    "!=",
    "<=",
    ">=",
    "+",
    "-",
    "*",
    "/",
    "%",
    "(",
    ")",
    "{",
    "}",
    ";",
    "=",
    "<",
    ">",
)

_ESCAPES: dict[str, str] = {"n": "\n", "t": "\t", '"': '"', "\\": "\\"}


@dataclasses.dataclass(frozen=True)
class Token:
    """A single lexical token."""

    kind: str
    text: str
    value: object
    offset: int


def _is_digit(ch: str) -> bool:
    return "0" <= ch <= "9"


def _is_ident_start(ch: str) -> bool:
    return ch == "_" or ch.isascii() and ch.isalpha()


def _is_ident_part(ch: str) -> bool:
    return _is_ident_start(ch) or _is_digit(ch)


def _scan_string(src: str, start: int) -> tuple[Token, int]:
    """Scan a double quoted string starting at the opening quote."""
    index = start + 1
    chunks: list[str] = []
    while True:
        if index >= len(src):
            raise LexError("unterminated string literal", start)
        ch = src[index]
        if ch == '"':
            value = "".join(chunks)
            return Token("STRING", value, value, start), index + 1
        if ch == "\n":
            raise LexError("newline inside string literal", index)
        if ch == "\\":
            if index + 1 >= len(src):
                raise LexError("unterminated string literal", start)
            escape = src[index + 1]
            if escape not in _ESCAPES:
                raise LexError(f"invalid escape sequence \\{escape}", index)
            chunks.append(_ESCAPES[escape])
            index += 2
            continue
        chunks.append(ch)
        index += 1


def _scan_exponent(src: str, index: int) -> int:
    """Return the index past an optional exponent part, validating its digits."""
    if index < len(src) and src[index] in "eE":
        cursor = index + 1
        if cursor < len(src) and src[cursor] in "+-":
            cursor += 1
        if cursor >= len(src) or not _is_digit(src[cursor]):
            raise LexError("malformed exponent in number literal", index)
        while cursor < len(src) and _is_digit(src[cursor]):
            cursor += 1
        return cursor
    return index


def _scan_number(src: str, start: int) -> tuple[Token, int]:
    """Scan an integer or float literal; ``1.`` and ``.5`` are errors."""
    index = start
    while index < len(src) and _is_digit(src[index]):
        index += 1
    if index < len(src) and src[index] == ".":
        if index + 1 >= len(src) or not _is_digit(src[index + 1]):
            raise LexError("float literal needs digits after the dot", index)
        index += 1
        while index < len(src) and _is_digit(src[index]):
            index += 1
        index = _scan_exponent(src, index)
        text = src[start:index]
        return Token("FLOAT", text, float(text), start), index
    text = src[start:index]
    return Token("INT", text, int(text), start), index


def _scan_word(src: str, start: int) -> tuple[Token, int]:
    index = start
    while index < len(src) and _is_ident_part(src[index]):
        index += 1
    text = src[start:index]
    kind = "KEYWORD" if text in KEYWORDS else "IDENT"
    return Token(kind, text, text, start), index


def _skip_trivia(src: str, index: int) -> int:
    """Skip whitespace and ``//`` comments, returning the next code index."""
    while index < len(src):
        ch = src[index]
        if ch.isspace():
            index += 1
        elif src.startswith("//", index):
            newline = src.find("\n", index)
            index = len(src) if newline == -1 else newline
        else:
            break
    return index


def tokenize(src: str) -> list[Token]:
    """Convert *src* into a list of tokens; no end-of-input token is emitted."""
    tokens: list[Token] = []
    index = 0
    while True:
        index = _skip_trivia(src, index)
        if index >= len(src):
            return tokens
        ch = src[index]
        if _is_digit(ch):
            token, index = _scan_number(src, index)
        elif _is_ident_start(ch):
            token, index = _scan_word(src, index)
        elif ch == '"':
            token, index = _scan_string(src, index)
        else:
            for op in _OPERATORS:
                if src.startswith(op, index):
                    token = Token("OP", op, op, index)
                    index += len(op)
                    break
            else:
                raise LexError(f"unexpected character {ch!r}", index)
        tokens.append(token)
