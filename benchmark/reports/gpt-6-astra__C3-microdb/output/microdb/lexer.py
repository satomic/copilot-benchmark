"""A position-preserving lexer, without a parser generator."""

from dataclasses import dataclass
import re

from .errors import LexError


KEYWORDS = frozenset(
    "SELECT DISTINCT FROM INNER LEFT JOIN ON WHERE GROUP BY HAVING ORDER ASC DESC "
    "LIMIT OFFSET AS AND OR NOT IS NULL TRUE FALSE".split()
)
_NUMBER = re.compile(r"(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?")
_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


@dataclass(frozen=True)
class Token:
    kind: str
    value: object
    offset: int
    end: int


def _text(source: str, start: int) -> Token:
    position = start + 1
    value = []
    while position < len(source):
        if source[position] != "'":
            value.append(source[position])
            position += 1
        elif position + 1 < len(source) and source[position + 1] == "'":
            value.append("'")
            position += 2
        else:
            return Token("TEXT", "".join(value), start, position + 1)
    raise LexError("Unterminated text literal", start)


def tokenize(source: str) -> list[Token]:
    tokens = []
    position = 0
    while position < len(source):
        char = source[position]
        if char.isspace():
            position += 1
            continue
        if source.startswith("--", position):
            end = source.find("\n", position)
            position = len(source) if end == -1 else end + 1
            continue
        if char == "'":
            token = _text(source, position)
        elif match := _NUMBER.match(source, position):
            text = match.group()
            floating = any(c in text for c in ".eE")
            token = Token("FLOAT" if floating else "INT",
                          float(text) if floating else int(text), position, match.end())
        elif match := _IDENT.match(source, position):
            text = match.group()
            kind = text.upper() if text.upper() in KEYWORDS else "IDENT"
            token = Token(kind, text, position, match.end())
        elif source[position:position + 2] in ("<>", "<=", ">="):
            text = source[position:position + 2]
            token = Token(text, text, position, position + 2)
        elif char in "=<>+-*/%(),.":
            token = Token(char, char, position, position + 1)
        else:
            raise LexError(f"Unexpected character {char!r}", position)
        tokens.append(token)
        position = token.end
    tokens.append(Token("EOF", None, len(source), len(source)))
    return tokens
