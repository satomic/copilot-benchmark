from dataclasses import dataclass
import re

from .errors import LexError


@dataclass(frozen=True)
class Token:
    kind: str
    text: str
    value: object
    offset: int


KEYWORDS = frozenset(
    ("let", "print", "if", "else", "while", "true", "false", "and", "or", "not")
)
_NUMBER = re.compile(r"[0-9]+(?:\.[0-9]+(?:[eE][+-]?[0-9]+)?)?")
_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_COMMENT = re.compile(r"//[^\r\n]*")
_ESCAPES = {"n": "\n", "t": "\t", '"': '"', "\\": "\\"}
_SINGLE = frozenset("+-*/%(){};=<>")
_DOUBLE = frozenset(("==", "!=", "<=", ">="))


def _string(src: str, start: int) -> tuple[Token, int]:
    chars: list[str] = []
    index = start + 1
    while index < len(src):
        char = src[index]
        if char == '"':
            value = "".join(chars)
            return Token("STRING", value, value, start), index + 1
        if char in "\r\n":
            raise LexError("Literal newline in string", index)
        if char == "\\":
            index += 1
            if index == len(src):
                raise LexError("Unterminated string", start)
            if src[index] not in _ESCAPES:
                raise LexError("Invalid string escape", index - 1)
            char = _ESCAPES[src[index]]
        chars.append(char)
        index += 1
    raise LexError("Unterminated string", start)


def _number(src: str, start: int) -> tuple[Token, int]:
    match = _NUMBER.match(src, start)
    assert match is not None
    text = match.group()
    end = match.end()
    if end < len(src) and src[end] in ".eE":
        raise LexError("Malformed number", end)
    kind = "FLOAT" if "." in text else "INT"
    try:
        value = float(text) if kind == "FLOAT" else int(text)
    except ValueError as error:
        raise LexError("Invalid number", start) from error
    return Token(kind, text, value, start), end


def tokenize(src: str) -> list[Token]:
    tokens: list[Token] = []
    index = 0
    while index < len(src):
        char = src[index]
        if char.isspace():
            index += 1
        elif src.startswith("//", index):
            match = _COMMENT.match(src, index)
            assert match is not None
            index = match.end()
        elif char == '"':
            token, index = _string(src, index)
            tokens.append(token)
        elif char in "0123456789":
            token, index = _number(src, index)
            tokens.append(token)
        elif match := _IDENT.match(src, index):
            text = match.group()
            kind = "KEYWORD" if text in KEYWORDS else "IDENT"
            tokens.append(Token(kind, text, text, index))
            index = match.end()
        elif src[index:index + 2] in _DOUBLE:
            text = src[index:index + 2]
            tokens.append(Token("OP", text, text, index))
            index += 2
        elif char in _SINGLE:
            tokens.append(Token("OP", char, char, index))
            index += 1
        else:
            raise LexError(f"Unexpected character {char!r}", index)
    return tokens
