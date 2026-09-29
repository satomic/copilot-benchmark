import dataclasses
import re

from microvm.errors import LexError

_TOKEN_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("STRING", re.compile(r'"([^"\\]*(?:\\.?[^"\\]*)*)"')),
    ("FLOAT", re.compile(r'\d+\.\d+(?:[eE][+-]?\d+)?')),
    ("INT", re.compile(r'\d+')),
    ("IDENT", re.compile(r'[A-Za-z_][A-Za-z0-9_]*')),
    ("OP", re.compile(r'==|!=|<=|>=|[+\-*/%(){};=<>]')),
]

_ESCAPE_MAP = {"n": "\n", "t": "\t", '"': '"', "\\": "\\"}

_KEYWORDS = {
    "let", "print", "if", "else", "while", "true", "false", "and", "or", "not",
}


@dataclasses.dataclass(frozen=True)
class Token:
    kind: str
    text: str
    value: object
    offset: int


def _decode_string(raw: str) -> str:
    chars: list[str] = []
    i = 0
    while i < len(raw):
        if raw[i] == "\\":
            if i + 1 >= len(raw):
                raise ValueError
            ch = raw[i + 1]
            if ch in _ESCAPE_MAP:
                chars.append(_ESCAPE_MAP[ch])
            else:
                raise LexError(f"Invalid escape sequence: \\{ch}", 0)
            i += 2
        else:
            chars.append(raw[i])
            i += 1
    return "".join(chars)


def tokenize(src: str) -> list[Token]:
    tokens: list[Token] = []
    pos = 0
    while pos < len(src):
        ch = src[pos]
        if ch in " \t\r\n":
            pos += 1
            continue
        if ch == "/" and pos + 1 < len(src) and src[pos + 1] == "/":
            end = src.find("\n", pos)
            if end == -1:
                break
            pos = end + 1
            continue

        matched = False
        for kind, pattern in _TOKEN_PATTERNS:
            m = pattern.match(src, pos)
            if m is not None:
                raw = m.group(0)
                if kind == "STRING":
                    inner = raw[1:-1]
                    value = _decode_string(inner)
                    tokens.append(Token("STRING", value, value, pos))
                elif kind == "FLOAT":
                    tokens.append(Token("FLOAT", raw, float(raw), pos))
                elif kind == "INT":
                    tokens.append(Token("INT", raw, int(raw), pos))
                elif kind == "IDENT":
                    text = raw
                    if text in _KEYWORDS:
                        tokens.append(Token("KEYWORD", text, text, pos))
                    else:
                        tokens.append(Token("IDENT", text, text, pos))
                else:
                    tokens.append(Token(kind, raw, raw, pos))
                pos = m.end()
                matched = True
                break

        if not matched:
            raise LexError(f"Unexpected character: {ch!r}", pos)

    return tokens