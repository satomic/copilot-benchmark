from dataclasses import dataclass

from .errors import LexError


@dataclass(frozen=True)
class Token:
    kind: str
    text: str
    value: object
    offset: int


_KEYWORDS = {"let", "print", "if", "else", "while", "true", "false",
             "and", "or", "not"}
_SINGLE = set("+-*/%(){};=<>")


def tokenize(src: str) -> list[Token]:
    tokens: list[Token] = []
    i = 0
    while i < len(src):
        if src[i].isspace():
            i += 1
            continue
        if src.startswith("//", i):
            end = src.find("\n", i)
            i = len(src) if end < 0 else end + 1
            continue
        start = i
        char = src[i]
        if char in "0123456789":
            i = _number(src, i, tokens)
        elif (char.isalpha() and char.isascii()) or char == "_":
            i += 1
            while i < len(src) and ((src[i].isascii() and src[i].isalnum())
                                    or src[i] == "_"):
                i += 1
            text = src[start:i]
            kind = "KEYWORD" if text in _KEYWORDS else "IDENT"
            tokens.append(Token(kind, text, text, start))
        elif char == '"':
            token, i = _string(src, i)
            tokens.append(token)
        elif any(src.startswith(op, i) for op in ("==", "!=", "<=", ">=")):
            op = src[i:i + 2]
            i += 2
            tokens.append(Token("OP", op, op, start))
        elif char in _SINGLE:
            op = char
            i += 1
            tokens.append(Token("OP", op, op, start))
        else:
            raise LexError(f"unexpected character {char!r}", i)
    return tokens


def _number(src: str, start: int, tokens: list[Token]) -> int:
    i = start
    while i < len(src) and src[i] in "0123456789":
        i += 1
    floating = False
    if i < len(src) and src[i] == ".":
        floating = True
        i += 1
        digit_start = i
        while i < len(src) and src[i] in "0123456789":
            i += 1
        if i == digit_start:
            raise LexError("float requires digits after decimal point", i - 1)
    if i < len(src) and src[i] in "eE":
        floating = True
        exp = i
        i += 1
        if i < len(src) and src[i] in "+-":
            i += 1
        digit_start = i
        while i < len(src) and src[i] in "0123456789":
            i += 1
        if i == digit_start:
            raise LexError("invalid float exponent", exp)
    text = src[start:i]
    try:
        value: object = float(text) if floating else int(text)
    except ValueError as exc:
        raise LexError("invalid number", start) from exc
    tokens.append(Token("FLOAT" if floating else "INT", text, value, start))
    return i


def _string(src: str, start: int) -> tuple[Token, int]:
    decoded: list[str] = []
    i = start + 1
    escapes = {"n": "\n", "t": "\t", '"': '"', "\\": "\\"}
    while i < len(src):
        char = src[i]
        if char == '"':
            value = "".join(decoded)
            return Token("STRING", value, value, start), i + 1
        if char in "\r\n":
            raise LexError("newline in string", i)
        if char == "\\":
            if i + 1 >= len(src) or src[i + 1] not in escapes:
                raise LexError("invalid string escape", i)
            decoded.append(escapes[src[i + 1]])
            i += 2
        else:
            decoded.append(char)
            i += 1
    raise LexError("unterminated string", start)
