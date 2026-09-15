"""Tokenizer for minilang."""

import re

from .errors import LexError

KEYWORDS = frozenset({"true", "false", "and", "or", "not"})

# A number never ends with '.', so "1." lexes as NUMBER(1) followed by a
# stray '.', which is then reported as a LexError at the dot's position.
_NUMBER_RE = re.compile(r"\d+(?:\.\d+)?(?:[eE][+-]?\d+)?|\.\d+(?:[eE][+-]?\d+)?")
_IDENT_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")

_ESCAPES = {"n": "\n", "t": "\t", "r": "\r", '"': '"', "\\": "\\"}

_TWO_CHAR_OPS = frozenset({"==", "!=", "<=", ">="})
_ONE_CHAR_OPS = frozenset("+-*/%^<>(),")

_WHITESPACE = frozenset(" \t\r\n")


class Token:
    __slots__ = ("kind", "value", "position")

    def __init__(self, kind, value, position):
        self.kind = kind  # NUMBER, STRING, IDENT, KEYWORD or OP
        self.value = value
        self.position = position

    def __repr__(self):
        return f"Token({self.kind}, {self.value!r}, {self.position})"


def tokenize(source):
    """Turn source text into a list of tokens (no EOF token)."""
    tokens = []
    i = 0
    n = len(source)
    while i < n:
        c = source[i]

        if c in _WHITESPACE:
            i += 1
            continue

        if c == "#":  # comment to end of line
            while i < n and source[i] != "\n":
                i += 1
            continue

        if c.isdigit() or (c == "." and i + 1 < n and source[i + 1].isdigit()):
            match = _NUMBER_RE.match(source, i)
            tokens.append(Token("NUMBER", float(match.group(0)), i))
            i = match.end()
            continue

        if c == '"':
            start = i
            i += 1
            chars = []
            while True:
                if i >= n:
                    raise LexError("unterminated string", start)
                ch = source[i]
                if ch == '"':
                    i += 1
                    break
                if ch == "\n":
                    raise LexError("newline in string literal", i)
                if ch == "\\":
                    if i + 1 >= n:
                        raise LexError("unterminated string", start)
                    esc = source[i + 1]
                    if esc not in _ESCAPES:
                        raise LexError(f"invalid escape sequence: \\{esc}", i)
                    chars.append(_ESCAPES[esc])
                    i += 2
                    continue
                chars.append(ch)
                i += 1
            tokens.append(Token("STRING", "".join(chars), start))
            continue

        match = _IDENT_RE.match(source, i)
        if match is not None:
            text = match.group(0)
            kind = "KEYWORD" if text in KEYWORDS else "IDENT"
            tokens.append(Token(kind, text, i))
            i = match.end()
            continue

        two = source[i : i + 2]
        if two in _TWO_CHAR_OPS:
            tokens.append(Token("OP", two, i))
            i += 2
            continue

        if c in _ONE_CHAR_OPS:
            tokens.append(Token("OP", c, i))
            i += 1
            continue

        if c == "=":
            raise LexError("single '=' is not an operator (did you mean '=='?)", i)

        raise LexError(f"unexpected character: {c!r}", i)

    return tokens
