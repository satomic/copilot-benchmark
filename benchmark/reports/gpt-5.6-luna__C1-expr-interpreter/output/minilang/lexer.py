import re
from dataclasses import dataclass
from .errors import LexError


@dataclass(frozen=True)
class Token:
    kind: str
    value: object
    position: int


_number = re.compile(r"(?:\d+\.\d+|\d+|\.\d+)(?:[eE][+-]?\d+)?")
_ident = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_keywords = {"true", "false", "and", "or", "not"}
_two_ops = {"==", "!=", "<=", ">="}
_one_ops = set("+-*/%^<>() ,")


def tokenize(source: str) -> list:
    result = []
    i = 0
    while i < len(source):
        c = source[i]
        if c.isspace():
            i += 1
            continue
        if c == "#":
            end = source.find("\n", i)
            i = len(source) if end < 0 else end
            continue
        if c == '"':
            start = i
            i += 1
            chars = []
            while i < len(source):
                c = source[i]
                if c == '"':
                    i += 1
                    result.append(Token("STRING", "".join(chars), start))
                    break
                if c in "\r\n":
                    raise LexError("unterminated string", start)
                if c == "\\":
                    i += 1
                    if i >= len(source):
                        raise LexError("unterminated string", start)
                    esc = source[i]
                    maps = {"n": "\n", "t": "\t", "r": "\r", '"': '"', "\\": "\\"}
                    if esc not in maps:
                        raise LexError("invalid escape", i - 1)
                    chars.append(maps[esc])
                else:
                    chars.append(c)
                i += 1
            else:
                raise LexError("unterminated string", start)
            continue
        m = _number.match(source, i)
        if m:
            text = m.group()
            if source[i].isdigit() and i + len(text) < len(source) and source[i + len(text)] == ".":
                raise LexError("number may not end with '.'", i + len(text))
            if text.endswith("."):
                raise LexError("number may not end with '.'", i + len(text) - 1)
            try:
                value = float(text)
            except ValueError:
                raise LexError("invalid number", i)
            result.append(Token("NUMBER", value, i))
            i = m.end()
            continue
        m = _ident.match(source, i)
        if m:
            value = m.group()
            result.append(Token("KEYWORD" if value in _keywords else "IDENT", value, i))
            i = m.end()
            continue
        op = source[i:i + 2]
        if op in _two_ops:
            result.append(Token("OP", op, i))
            i += 2
            continue
        if c == "=":
            raise LexError("unexpected '='", i)
        if c == "!":
            raise LexError("unexpected '!'", i)
        if c in _one_ops:
            result.append(Token("OP", c, i))
            i += 1
            continue
        raise LexError(f"unexpected character: {c}", i)
    return result
