from dataclasses import dataclass
import re

from .errors import LexError


@dataclass(frozen=True)
class Token:
    kind: str
    text: str
    value: object
    offset: int


_KEYWORDS = frozenset(
    ("let", "print", "if", "else", "while", "true", "false", "and", "or", "not")
)
_FLOAT = re.compile(r"\d+\.\d+(?:[eE][+-]?\d+)?")
_INT = re.compile(r"\d+")
_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_TWO_CHAR_OPS = frozenset(("==", "!=", "<=", ">="))
_ONE_CHAR_OPS = frozenset("+-*/%(){};=<>")
_ESCAPES = {"n": "\n", "t": "\t", '"': '"', "\\": "\\"}


def _string_token(src: str, start: int) -> tuple[Token, int]:
    chars: list[str] = []
    pos = start + 1
    while pos < len(src):
        char = src[pos]
        if char == '"':
            value = "".join(chars)
            return Token("STRING", value, value, start), pos + 1
        if char in "\r\n":
            raise LexError(f"newline in string at offset {pos}", pos)
        if char == "\\":
            if pos + 1 >= len(src) or src[pos + 1] not in _ESCAPES:
                raise LexError(f"invalid string escape at offset {pos}", pos)
            chars.append(_ESCAPES[src[pos + 1]])
            pos += 2
        else:
            chars.append(char)
            pos += 1
    raise LexError(f"unterminated string at offset {start}", start)


def tokenize(src: str) -> list[Token]:
    tokens: list[Token] = []
    pos = 0
    while pos < len(src):
        if src[pos].isspace():
            pos += 1
            continue
        if src.startswith("//", pos):
            newline = src.find("\n", pos + 2)
            pos = len(src) if newline < 0 else newline + 1
            continue
        if src[pos] == '"':
            token, pos = _string_token(src, pos)
            tokens.append(token)
            continue
        match = _FLOAT.match(src, pos)
        if match:
            text = match.group()
            tokens.append(Token("FLOAT", text, float(text), pos))
            pos = match.end()
            continue
        match = _INT.match(src, pos)
        if match:
            text = match.group()
            tokens.append(Token("INT", text, int(text), pos))
            pos = match.end()
            continue
        match = _IDENT.match(src, pos)
        if match:
            text = match.group()
            kind = "KEYWORD" if text in _KEYWORDS else "IDENT"
            tokens.append(Token(kind, text, text, pos))
            pos = match.end()
            continue
        two = src[pos:pos + 2]
        if two in _TWO_CHAR_OPS:
            tokens.append(Token("OP", two, two, pos))
            pos += 2
            continue
        if src[pos] in _ONE_CHAR_OPS:
            text = src[pos]
            tokens.append(Token("OP", text, text, pos))
            pos += 1
            continue
        raise LexError(f"unexpected character at offset {pos}", pos)
    return tokens
