from dataclasses import dataclass
import re

from .errors import LexError


KEYWORDS = frozenset({"true", "false", "and", "or", "not"})
_NUMBER = re.compile(r"(?:[0-9]+(?:\.[0-9]+)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?")
_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_ESCAPES = {"n": "\n", "t": "\t", "r": "\r", '"': '"', "\\": "\\"}


@dataclass(frozen=True)
class Token:
    kind: str
    value: float | str
    position: int


def tokenize(source: str) -> list[Token]:
    tokens: list[Token] = []
    index = 0
    while index < len(source):
        char = source[index]
        if char.isspace():
            index += 1
            continue
        if char == "#":
            while index < len(source) and source[index] not in "\r\n":
                index += 1
            continue
        start = index
        if char == '"':
            index += 1
            contents: list[str] = []
            while index < len(source) and source[index] != '"':
                char = source[index]
                if char in "\r\n":
                    raise LexError("literal newline in string", index)
                if char == "\\":
                    escape_position = index
                    index += 1
                    if index == len(source):
                        raise LexError("unterminated string", start)
                    if source[index] not in _ESCAPES:
                        # An invalid escape is located at its introducing backslash.
                        raise LexError("invalid escape sequence", escape_position)
                    char = _ESCAPES[source[index]]
                contents.append(char)
                index += 1
            if index == len(source):
                raise LexError("unterminated string", start)
            index += 1
            tokens.append(Token("STRING", "".join(contents), start))
            continue
        match = _NUMBER.match(source, index)
        if match is not None:
            index = match.end()
            if index < len(source) and source[index] in ".eE":
                raise LexError("invalid number", index)
            tokens.append(Token("NUMBER", float(match.group()), start))
            continue
        match = _IDENT.match(source, index)
        if match is not None:
            value = match.group()
            tokens.append(Token("KEYWORD" if value in KEYWORDS else "IDENT", value, start))
            index = match.end()
            continue
        pair = source[index:index + 2]
        if pair in {"==", "!=", "<=", ">="}:
            tokens.append(Token("OP", pair, start))
            index += 2
        elif char in "+-*/%^<>(),":
            tokens.append(Token("OP", char, start))
            index += 1
        else:
            raise LexError(f"unexpected character: {char!r}", index)
    return tokens
