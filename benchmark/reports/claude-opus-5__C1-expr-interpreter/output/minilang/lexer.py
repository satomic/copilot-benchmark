"""Lexer: turns minilang source text into a flat list of tokens."""

import re

from .errors import LexError

KEYWORDS = frozenset({"true", "false", "and", "or", "not"})

#: Token kinds produced by :func:`tokenize` (rule 32).
TOKEN_KINDS = ("NUMBER", "STRING", "IDENT", "KEYWORD", "OP")

_NUMBER_RE = re.compile(r"(?:[0-9]+(?:\.[0-9]+)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?")
_IDENT_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")

_TWO_CHAR_OPS = ("==", "!=", "<=", ">=")
_ONE_CHAR_OPS = frozenset("+-*/%^<>(),")

_STRING_ESCAPES = {
    "n": "\n",
    "t": "\t",
    "r": "\r",
    '"': '"',
    "\\": "\\",
}


class Token:
    """A single lexical token."""

    __slots__ = ("kind", "value", "position")

    def __init__(self, kind, value, position):
        self.kind = kind
        self.value = value
        self.position = position

    def __repr__(self):
        return f"Token({self.kind!r}, {self.value!r}, {self.position!r})"

    def __eq__(self, other):
        if not isinstance(other, Token):
            return NotImplemented
        return (
            self.kind == other.kind
            and self.value == other.value
            and self.position == other.position
        )

    def __hash__(self):
        return hash((self.kind, self.value, self.position))


def _lex_string(source, start):
    """Lex a double-quoted string starting at ``start``; return (token, next)."""
    i = start + 1
    chars = []
    n = len(source)
    while True:
        if i >= n:
            raise LexError("unterminated string", start)
        ch = source[i]
        if ch == '"':
            return Token("STRING", "".join(chars), start), i + 1
        if ch == "\n":
            # Rule 4: a literal newline may not appear inside a string.
            raise LexError("unterminated string", start)
        if ch == "\\":
            if i + 1 >= n:
                raise LexError("unterminated string", start)
            esc = source[i + 1]
            if esc not in _STRING_ESCAPES:
                raise LexError(f"invalid escape sequence: \\{esc}", i)
            chars.append(_STRING_ESCAPES[esc])
            i += 2
            continue
        chars.append(ch)
        i += 1


def tokenize(source):
    """Split ``source`` into a list of :class:`Token` objects.

    Raises :class:`LexError` on any character that cannot start a token.
    """
    if not isinstance(source, str):
        raise TypeError("source must be a string")

    tokens = []
    i = 0
    n = len(source)
    while i < n:
        ch = source[i]

        if ch in " \t\r\n\f\v":
            i += 1
            continue

        if ch == "#":
            while i < n and source[i] != "\n":
                i += 1
            continue

        if ch == '"':
            token, i = _lex_string(source, i)
            tokens.append(token)
            continue

        if ch.isdigit() or (ch == "." and i + 1 < n and source[i + 1].isdigit()):
            match = _NUMBER_RE.match(source, i)
            if match is None:
                raise LexError(f"invalid number literal: {ch}", i)
            end = match.end()
            # `1.` and `1.e3` are invalid, and `1abc` is not two tokens either.
            if end < n and (source[end] == "." or source[end].isalnum() or source[end] == "_"):
                raise LexError("invalid number literal", i)
            tokens.append(Token("NUMBER", float(match.group()), i))
            i = end
            continue

        if ch.isalpha() or ch == "_":
            match = _IDENT_RE.match(source, i)
            text = match.group()
            kind = "KEYWORD" if text in KEYWORDS else "IDENT"
            tokens.append(Token(kind, text, i))
            i = match.end()
            continue

        two = source[i : i + 2]
        if two in _TWO_CHAR_OPS:
            tokens.append(Token("OP", two, i))
            i += 2
            continue

        if ch == "=":
            # A lone `=` is not part of the language (rule 7).
            raise LexError("unexpected character: '='", i)

        if ch == "!":
            raise LexError("unexpected character: '!'", i)

        if ch in _ONE_CHAR_OPS:
            tokens.append(Token("OP", ch, i))
            i += 1
            continue

        raise LexError(f"unexpected character: {ch!r}", i)

    return tokens
