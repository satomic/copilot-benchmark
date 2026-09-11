import dataclasses
from .errors import LexError


@dataclasses.dataclass(frozen=True)
class Token:
    kind: str
    text: str
    value: object
    offset: int


KEYWORDS = {"let", "print", "if", "else", "while", "true", "false", "and", "or", "not"}


def _scan_float(src: str, start: int, i: int, offset: int) -> tuple[Token, int]:
    if i < len(src) and src[i] in "eE":
        i += 1
        if i < len(src) and src[i] in "+-":
            i += 1
        if not (i < len(src) and src[i].isdigit()):
            raise LexError("Invalid exponent", offset)
        while i < len(src) and src[i].isdigit():
            i += 1
    text = src[start:i]
    return Token("FLOAT", text, float(text), offset), i


def _scan_number(src: str, i: int) -> tuple[Token, int]:
    start, offset = i, i
    while i < len(src) and src[i].isdigit():
        i += 1
    if i < len(src) and src[i] == ".":
        i += 1
        if not (i < len(src) and src[i].isdigit()):
            raise LexError("Invalid float", offset)
        while i < len(src) and src[i].isdigit():
            i += 1
        return _scan_float(src, start, i, offset)
    if i < len(src) and src[i] == ".":
        raise LexError("Invalid float", offset)
    text = src[start:i]
    return Token("INT", text, int(text), offset), i


def _scan_string(src: str, i: int) -> tuple[Token, int]:
    offset = i
    i += 1
    val = []
    while i < len(src) and src[i] != '"':
        if src[i] == "\n":
            raise LexError("Unterminated string", offset)
        if src[i] == "\\":
            if i + 1 >= len(src):
                raise LexError("Unterminated string", offset)
            i += 1
            escapes = {"n": "\n", "t": "\t", '"': '"', "\\": "\\"}
            if src[i] not in escapes:
                raise LexError("Invalid escape", offset)
            val.append(escapes[src[i]])
            i += 1
        else:
            val.append(src[i])
            i += 1
    if i >= len(src):
        raise LexError("Unterminated string", offset)
    i += 1
    decoded = "".join(val)
    return Token("STRING", decoded, decoded, offset), i


def _scan_ident(src: str, i: int) -> tuple[Token, int]:
    start, offset = i, i
    while i < len(src) and (src[i].isalnum() or src[i] == "_"):
        i += 1
    text = src[start:i]
    kind = "KEYWORD" if text in KEYWORDS else "IDENT"
    return Token(kind, text, text, offset), i


def tokenize(src: str) -> list[Token]:
    tokens = []
    i = 0
    while i < len(src):
        if src[i].isspace():
            i += 1
        elif i + 1 < len(src) and src[i:i+2] == "//":
            while i < len(src) and src[i] != "\n":
                i += 1
        elif src[i].isdigit():
            tok, i = _scan_number(src, i)
            tokens.append(tok)
        elif src[i] == '"':
            tok, i = _scan_string(src, i)
            tokens.append(tok)
        elif src[i].isalpha() or src[i] == "_":
            tok, i = _scan_ident(src, i)
            tokens.append(tok)
        elif src[i:i+2] == "==":
            tokens.append(Token("OP", "==", "==", i))
            i += 2
        elif src[i:i+2] == "!=":
            tokens.append(Token("OP", "!=", "!=", i))
            i += 2
        elif src[i:i+2] == "<=":
            tokens.append(Token("OP", "<=", "<=", i))
            i += 2
        elif src[i:i+2] == ">=":
            tokens.append(Token("OP", ">=", ">=", i))
            i += 2
        elif src[i] in "+-*/%(){}=;<>":
            tokens.append(Token("OP", src[i], src[i], i))
            i += 1
        elif src[i] == ".":
            raise LexError("Invalid float", i)
        else:
            raise LexError("Unexpected character", i)
    return tokens
