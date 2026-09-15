"""Tokenizer for the microvm language."""

import dataclasses

from .errors import LexError

KEYWORDS: frozenset[str] = frozenset(
    {"let", "print", "if", "else", "while", "true", "false", "and", "or", "not"}
)

_ESCAPES: dict[str, str] = {"n": "\n", "t": "\t", '"': '"', "\\": "\\"}

# Longest match wins: two-character operators first.
_OPS: tuple[str, ...] = (
    "==", "!=", "<=", ">=", "+", "-", "*", "/", "%", "(", ")", "{", "}", ";", "=", "<", ">",
)


@dataclasses.dataclass(frozen=True)
class Token:
    kind: str      # "INT" | "FLOAT" | "STRING" | "IDENT" | "KEYWORD" | "OP"
    text: str      # the source lexeme (for STRING: the decoded value)
    value: object  # INT -> int, FLOAT -> float, STRING -> decoded str, else same as text
    offset: int    # zero-based character offset of the first character


def _read_number(src: str, start: int) -> tuple[Token, int]:
    """Read an integer or float literal starting at ``start``."""
    n = len(src)
    i = start
    while i < n and src[i].isdigit():
        i += 1
    is_float = False
    if i < n and src[i] == ".":
        is_float = True
        i += 1
        if i >= n or not src[i].isdigit():
            raise LexError("expected digit after '.'", i if i < n else n)
        while i < n and src[i].isdigit():
            i += 1
    if i < n and src[i] in "eE":
        is_float = True
        i += 1
        if i < n and src[i] in "+-":
            i += 1
        if i >= n or not src[i].isdigit():
            raise LexError("expected digit in exponent", i)
        while i < n and src[i].isdigit():
            i += 1
    text = src[start:i]
    if is_float:
        return Token("FLOAT", text, float(text), start), i
    return Token("INT", text, int(text), start), i


def _read_string(src: str, start: int) -> tuple[Token, int]:
    """Read a double-quoted string literal starting at ``start``."""
    parts: list[str] = []
    i = start + 1
    n = len(src)
    while i < n:
        ch = src[i]
        if ch == '"':
            value = "".join(parts)
            return Token("STRING", value, value, start), i + 1
        if ch == "\n":
            raise LexError("literal newline in string", i)
        if ch == "\\":
            if i + 1 >= n or src[i + 1] not in _ESCAPES:
                raise LexError("invalid escape sequence", i)
            parts.append(_ESCAPES[src[i + 1]])
            i += 2
        else:
            parts.append(ch)
            i += 1
    raise LexError("unterminated string", start)


def _read_ident(src: str, start: int) -> tuple[Token, int]:
    """Read an identifier or keyword starting at ``start``."""
    i = start
    n = len(src)
    while i < n and (src[i].isalnum() or src[i] == "_"):
        i += 1
    text = src[start:i]
    if text in KEYWORDS:
        return Token("KEYWORD", text, text, start), i
    return Token("IDENT", text, text, start), i


def tokenize(src: str) -> list[Token]:
    """Split ``src`` into tokens; raise ``LexError`` on malformed input."""
    tokens: list[Token] = []
    i = 0
    n = len(src)
    while i < n:
        ch = src[i]
        if ch in " \t\r\n":
            i += 1
            continue
        if src.startswith("//", i):
            j = src.find("\n", i)
            i = n if j == -1 else j + 1
            continue
        if ch.isdigit():
            tok, i = _read_number(src, i)
        elif ch == '"':
            tok, i = _read_string(src, i)
        elif ch.isalpha() or ch == "_":
            tok, i = _read_ident(src, i)
        else:
            tok = None
            for op in _OPS:
                if src.startswith(op, i):
                    tok = Token("OP", op, op, i)
                    i += len(op)
                    break
            if tok is None:
                raise LexError(f"unexpected character {ch!r}", i)
        tokens.append(tok)
    return tokens
