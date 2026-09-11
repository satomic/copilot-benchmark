from dataclasses import dataclass
import re

from .errors import LexError


@dataclass(frozen=True)
class Token:
    kind: str
    text: str
    value: object
    offset: int


_KEYWORDS = frozenset("let print if else while true false and or not".split())
_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_ESCAPES = {"n": "\n", "t": "\t", '"': '"', "\\": "\\"}
_PAIRS = frozenset(("==", "!=", "<=", ">="))
_SINGLES = frozenset("+-*/%(){};=<>")


def _string(src: str, start: int) -> tuple[Token, int]:
    chars: list[str] = []
    pos = start + 1
    while pos < len(src):
        char = src[pos]
        if char == '"':
            value = "".join(chars)
            return Token("STRING", value, value, start), pos + 1
        if char in "\r\n":
            raise LexError("Literal newline in string", pos)
        if char == "\\":
            if pos + 1 >= len(src):
                raise LexError("Unterminated string", start)
            escaped = src[pos + 1]
            if escaped not in _ESCAPES:
                raise LexError("Unknown string escape", pos)
            chars.append(_ESCAPES[escaped])
            pos += 2
        else:
            chars.append(char)
            pos += 1
    raise LexError("Unterminated string", start)


def _number(src: str, start: int) -> tuple[Token, int]:
    pos = start
    while pos < len(src) and src[pos] in "0123456789":
        pos += 1
    kind = "INT"
    if pos < len(src) and src[pos] == ".":
        kind = "FLOAT"
        pos += 1
        if pos == len(src) or src[pos] not in "0123456789":
            raise LexError("Expected digits after decimal point", pos)
        while pos < len(src) and src[pos] in "0123456789":
            pos += 1
        if pos < len(src) and src[pos] in "eE":
            pos += 1
            if pos < len(src) and src[pos] in "+-":
                pos += 1
            if pos == len(src) or src[pos] not in "0123456789":
                raise LexError("Expected exponent digits", pos)
            while pos < len(src) and src[pos] in "0123456789":
                pos += 1
    text = src[start:pos]
    if kind == "FLOAT":
        value = float(text)
    else:
        # Chunking avoids Python's configurable decimal-string digit limit.
        value = 0
        for index in range(0, len(text), 9):
            chunk = text[index:index + 9]
            value = value * 10 ** len(chunk) + int(chunk)
    return Token(kind, text, value, start), pos


def tokenize(src: str) -> list[Token]:
    tokens: list[Token] = []
    pos = 0
    while pos < len(src):
        char = src[pos]
        if char.isspace():
            pos += 1
            continue
        if src.startswith("//", pos):
            while pos < len(src) and src[pos] not in "\r\n":
                pos += 1
            continue
        if char == '"':
            token, pos = _string(src, pos)
        elif char in "0123456789":
            token, pos = _number(src, pos)
        else:
            match = _IDENT.match(src, pos)
            if match is not None:
                text = match.group()
                kind = "KEYWORD" if text in _KEYWORDS else "IDENT"
                token = Token(kind, text, text, pos)
                pos = match.end()
            else:
                text = src[pos:pos + 2]
                if text not in _PAIRS:
                    text = char
                    if text not in _SINGLES:
                        raise LexError(f"Unexpected character {char!r}", pos)
                token = Token("OP", text, text, pos)
                pos += len(text)
        tokens.append(token)
    return tokens
