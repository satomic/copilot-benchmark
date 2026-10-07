from dataclasses import dataclass

from .errors import LexError

KEYWORDS = {"true", "false", "and", "or", "not"}
ESCAPES = {"n": "\n", "t": "\t", "r": "\r", '"': '"', "\\": "\\"}
_DIGITS = "0123456789"
_IDENT_START = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ_"
_IDENT_PART = _IDENT_START + _DIGITS


@dataclass(frozen=True)
class Token:
    kind: str
    value: object
    position: int


def tokenize(source):
    tokens = []
    i = 0
    n = len(source)
    while i < n:
        c = source[i]
        if c in " \t\r\n":
            i += 1
        elif c == "#":
            while i < n and source[i] != "\n":
                i += 1
        elif c in _DIGITS or (c == "." and i + 1 < n and source[i + 1] in _DIGITS):
            start = i
            while i < n and source[i] in _DIGITS:
                i += 1
            if i < n and source[i] == ".":
                i += 1
                if i >= n or source[i] not in _DIGITS:
                    raise LexError("malformed number: cannot end with '.'", start)
                while i < n and source[i] in _DIGITS:
                    i += 1
            # An exponent only counts when digits follow; otherwise 'e' is left
            # to be lexed as an identifier (which the parser will reject).
            if i < n and source[i] in "eE":
                j = i + 1
                if j < n and source[j] in "+-":
                    j += 1
                if j < n and source[j] in _DIGITS:
                    while j < n and source[j] in _DIGITS:
                        j += 1
                    i = j
            tokens.append(Token("NUMBER", float(source[start:i]), start))
        elif c == '"':
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
                    raise LexError("newline in string", i)
                if ch == "\\":
                    if i + 1 >= n:
                        raise LexError("unterminated string", start)
                    esc = source[i + 1]
                    if esc not in ESCAPES:
                        raise LexError(f"invalid escape: \\{esc}", i)
                    chars.append(ESCAPES[esc])
                    i += 2
                else:
                    chars.append(ch)
                    i += 1
            tokens.append(Token("STRING", "".join(chars), start))
        elif c in _IDENT_START:
            start = i
            while i < n and source[i] in _IDENT_PART:
                i += 1
            word = source[start:i]
            tokens.append(Token("KEYWORD" if word in KEYWORDS else "IDENT", word, start))
        elif source.startswith(("==", "!=", "<=", ">="), i):
            tokens.append(Token("OP", source[i:i + 2], i))
            i += 2
        elif c in "+-*/%^<>(),":
            tokens.append(Token("OP", c, i))
            i += 1
        elif c == "=":
            raise LexError("unexpected '=' (did you mean '=='?)", i)
        else:
            raise LexError(f"unexpected character: {c!r}", i)
    return tokens
