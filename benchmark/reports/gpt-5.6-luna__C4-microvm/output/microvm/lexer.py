import dataclasses
import re
from .errors import LexError


@dataclasses.dataclass(frozen=True)
class Token:
    kind: str
    text: str
    value: object
    offset: int


_KEYWORDS = {"let", "print", "if", "else", "while", "true", "false", "and", "or", "not"}
_OPS = ("==", "!=", "<=", ">=", "+", "-", "*", "/", "%", "(", ")", "{", "}", ";", "=", "<", ">")


def tokenize(src: str) -> list[Token]:
    out: list[Token] = []
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
        c = src[i]
        if c == '"':
            i += 1
            chars: list[str] = []
            while i < len(src) and src[i] != '"':
                if src[i] in "\r\n":
                    raise LexError("newline in string", i)
                if src[i] == "\\":
                    i += 1
                    if i >= len(src) or src[i] not in "nt\"\\":
                        raise LexError("invalid escape", i)
                    chars.append({"n": "\n", "t": "\t", '"': '"', "\\": "\\"}[src[i]])
                else:
                    chars.append(src[i])
                i += 1
            if i >= len(src):
                raise LexError("unterminated string", start)
            i += 1
            text = "".join(chars)
            out.append(Token("STRING", text, text, start))
            continue
        if "0" <= c <= "9":
            m = re.match(r"[0-9]+(?:\.[0-9]+(?:[eE][+-]?[0-9]+)?)?", src[i:])
            assert m
            text = m.group(0)
            i += len(text)
            if i < len(src) and src[i] == ".":
                raise LexError("invalid float", i)
            if i < len(src) and src[i] in "eE":
                raise LexError("invalid exponent", i)
            kind = "FLOAT" if "." in text else "INT"
            out.append(Token(kind, text, float(text) if kind == "FLOAT" else int(text), start))
            continue
        if c == ".": raise LexError("unexpected character", i)
        if ("A" <= c <= "Z") or ("a" <= c <= "z") or c == "_":
            m = re.match(r"[A-Za-z_][A-Za-z0-9_]*", src[i:])
            assert m
            text = m.group(0)
            i += len(text)
            kind = "KEYWORD" if text in _KEYWORDS else "IDENT"
            out.append(Token(kind, text, text, start))
            continue
        op = next((x for x in _OPS if src.startswith(x, i)), None)
        if op:
            out.append(Token("OP", op, op, i)); i += len(op); continue
        raise LexError("unexpected character", i)
    return out
