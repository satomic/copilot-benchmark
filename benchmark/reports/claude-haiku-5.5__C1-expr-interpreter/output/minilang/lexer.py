"""Tokenizer for minilang."""

from .errors import LexError

KEYWORDS = frozenset({"true", "false", "and", "or", "not"})
_TWO_CHAR_OPS = frozenset({"==", "!=", "<=", ">="})
_ONE_CHAR_OPS = frozenset("+-*/%^<>(),")
_DIGITS = "0123456789"
_IDENT_START = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz_"
_IDENT_CHARS = _IDENT_START + _DIGITS
_WHITESPACE = " \t\r\n"
_ESCAPES = {"n": "\n", "t": "\t", "r": "\r", '"': '"', "\\": "\\"}


class Token:
    """A lexical token. ``kind`` is one of NUMBER, STRING, IDENT, KEYWORD, OP."""

    __slots__ = ("kind", "value", "position")

    def __init__(self, kind, value, position):
        self.kind = kind
        self.value = value
        self.position = position

    def __repr__(self):
        return f"Token({self.kind}, {self.value!r}, {self.position})"


def tokenize(source):
    """Split ``source`` into a list of Tokens (no EOF token)."""
    tokens = []
    i = 0
    n = len(source)
    while i < n:
        ch = source[i]
        if ch in _WHITESPACE:
            i += 1
        elif ch == "#":
            end = source.find("\n", i)
            i = n if end == -1 else end
        elif ch == '"':
            i = _lex_string(source, i, tokens)
        elif ch in _DIGITS or (ch == "." and i + 1 < n and source[i + 1] in _DIGITS):
            end = _scan_number(source, i)
            tokens.append(Token("NUMBER", float(source[i:end]), i))
            i = end
        elif ch in _IDENT_START:
            end = i + 1
            while end < n and source[end] in _IDENT_CHARS:
                end += 1
            word = source[i:end]
            kind = "KEYWORD" if word in KEYWORDS else "IDENT"
            tokens.append(Token(kind, word, i))
            i = end
        elif source[i:i + 2] in _TWO_CHAR_OPS:
            tokens.append(Token("OP", source[i:i + 2], i))
            i += 2
        elif ch in _ONE_CHAR_OPS:
            tokens.append(Token("OP", ch, i))
            i += 1
        elif ch == "=":
            raise LexError("unexpected '=' (did you mean '=='?)", i)
        else:
            raise LexError(f"unexpected character {ch!r}", i)
    return tokens


def _scan_number(src, start):
    """Return the end offset of the numeric literal starting at ``start``."""
    n = len(src)
    i = start
    while i < n and src[i] in _DIGITS:
        i += 1
    if i < n and src[i] == ".":
        i += 1
        if not (i < n and src[i] in _DIGITS):
            # "1." is not a valid number; the dot is the offending character
            raise LexError("malformed number: expected digit after '.'", i - 1)
        while i < n and src[i] in _DIGITS:
            i += 1
    if i < n and src[i] in "eE":
        j = i + 1
        if j < n and src[j] in "+-":
            j += 1
        if not (j < n and src[j] in _DIGITS):
            raise LexError("malformed number: expected exponent digits", i)
        i = j
        while i < n and src[i] in _DIGITS:
            i += 1
    return i


def _lex_string(src, start, tokens):
    """Lex a double-quoted string starting at ``start``; return the offset after it."""
    n = len(src)
    i = start + 1
    buf = []
    while True:
        if i >= n:
            raise LexError("unterminated string literal", start)
        ch = src[i]
        if ch == '"':
            break
        if ch == "\n":
            raise LexError("newline inside string literal", i)
        if ch == "\\":
            if i + 1 >= n:
                raise LexError("unterminated string literal", start)
            esc = src[i + 1]
            if esc not in _ESCAPES:
                raise LexError(f"invalid escape sequence '\\{esc}'", i)
            buf.append(_ESCAPES[esc])
            i += 2
            continue
        buf.append(ch)
        i += 1
    tokens.append(Token("STRING", "".join(buf), start))
    return i + 1
