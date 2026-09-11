"""Lexer for minilang: turns source text into a list of Token objects."""

from .errors import LexError

KEYWORDS = {"true", "false", "and", "or", "not"}

# Two-character operators must be checked before single-character ones.
_TWO_CHAR_OPS = ("==", "!=", "<=", ">=")
_ONE_CHAR_OPS = "+-*/%^(),<>"


class Token:
    __slots__ = ("kind", "value", "position")

    def __init__(self, kind: str, value, position: int):
        self.kind = kind
        self.value = value
        self.position = position

    def __repr__(self):
        return f"Token({self.kind!r}, {self.value!r}, {self.position})"

    def __eq__(self, other):
        if not isinstance(other, Token):
            return NotImplemented
        return (self.kind, self.value, self.position) == (
            other.kind,
            other.value,
            other.position,
        )


def tokenize(source: str) -> list:
    tokens = []
    i = 0
    n = len(source)

    while i < n:
        c = source[i]

        if c in " \t\n\r":
            i += 1
            continue

        if c == "#":
            while i < n and source[i] != "\n":
                i += 1
            continue

        if c.isdigit() or (c == "." and i + 1 < n and source[i + 1].isdigit()):
            start = i
            if c == ".":
                i += 1
                while i < n and source[i].isdigit():
                    i += 1
            else:
                while i < n and source[i].isdigit():
                    i += 1
                if i < n and source[i] == ".":
                    i += 1
                    if not (i < n and source[i].isdigit()):
                        raise LexError("number literal may not end with '.'", start)
                    while i < n and source[i].isdigit():
                        i += 1
            if i < n and source[i] in "eE":
                if i + 1 < n and (source[i + 1].isdigit() or source[i + 1] in "+-"):
                    i += 1
                    if i < n and source[i] in "+-":
                        i += 1
                    if not (i < n and source[i].isdigit()):
                        raise LexError("invalid number literal exponent", start)
                    while i < n and source[i].isdigit():
                        i += 1
            text = source[start:i]
            tokens.append(Token("NUMBER", float(text), start))
            continue

        if c == '"':
            start = i
            i += 1
            chars = []
            closed = False
            while i < n:
                ch = source[i]
                if ch == "\n":
                    break
                if ch == '"':
                    i += 1
                    closed = True
                    break
                if ch == "\\":
                    if i + 1 >= n or source[i + 1] == "\n":
                        break
                    esc = source[i + 1]
                    mapping = {"n": "\n", "t": "\t", "r": "\r", '"': '"', "\\": "\\"}
                    if esc not in mapping:
                        raise LexError(f"invalid escape sequence: \\{esc}", i)
                    chars.append(mapping[esc])
                    i += 2
                    continue
                chars.append(ch)
                i += 1
            if not closed:
                raise LexError("unterminated string literal", start)
            tokens.append(Token("STRING", "".join(chars), start))
            continue

        if c.isalpha() or c == "_":
            start = i
            i += 1
            while i < n and (source[i].isalnum() or source[i] == "_"):
                i += 1
            text = source[start:i]
            if text in KEYWORDS:
                tokens.append(Token("KEYWORD", text, start))
            else:
                tokens.append(Token("IDENT", text, start))
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
            raise LexError("unexpected '=' (did you mean '=='?)", i)

        raise LexError(f"unexpected character: {c!r}", i)

    return tokens
