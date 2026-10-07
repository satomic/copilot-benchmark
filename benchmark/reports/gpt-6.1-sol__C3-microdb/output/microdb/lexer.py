"""A positional lexer for the microdb query language."""

from dataclasses import dataclass
import re

from .errors import LexError


KEYWORDS = frozenset(
    "SELECT DISTINCT FROM INNER LEFT JOIN ON WHERE GROUP BY HAVING ORDER ASC DESC "
    "LIMIT OFFSET AS AND OR NOT IS NULL TRUE FALSE".split()
)
NUMBER = re.compile(r"(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?")
IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


@dataclass(frozen=True)
class Token:
    kind: str
    value: object
    offset: int
    end: int


def _string(source: str, start: int) -> Token:
    index = start + 1
    parts = []
    while index < len(source):
        if source[index] != "'":
            parts.append(source[index])
            index += 1
        elif index + 1 < len(source) and source[index + 1] == "'":
            parts.append("'")
            index += 2
        else:
            return Token("TEXT", "".join(parts), start, index + 1)
    raise LexError("Unterminated text literal", start)


def tokenize(source: str) -> list[Token]:
    tokens = []
    index = 0
    while index < len(source):
        char = source[index]
        if char.isspace():
            index += 1
            continue
        if source.startswith("--", index):
            end = source.find("\n", index)
            index = len(source) if end < 0 else end + 1
            continue
        if char == "'":
            token = _string(source, index)
        elif char in "0123456789" or (char == "." and index + 1 < len(source)
                                       and source[index + 1] in "0123456789"):
            match = NUMBER.match(source, index)
            text = match.group()
            floating = any(mark in text for mark in ".eE")
            token = Token("FLOAT" if floating else "INT",
                          float(text) if floating else int(text), index, match.end())
        elif IDENTIFIER.match(source, index):
            match = IDENTIFIER.match(source, index)
            text = match.group()
            kind = text.upper() if text.upper() in KEYWORDS else "IDENT"
            token = Token(kind, text, index, match.end())
        elif source[index:index + 2] in ("<>", "<=", ">="):
            text = source[index:index + 2]
            token = Token(text, text, index, index + 2)
        elif char in "=<>+-*/%(),.":
            token = Token(char, char, index, index + 1)
        else:
            raise LexError(f"Unexpected character {char!r}", index)
        tokens.append(token)
        index = token.end
    tokens.append(Token("EOF", None, len(source), len(source)))
    return tokens
