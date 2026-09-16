from dataclasses import dataclass
import re
from .errors import LexError


@dataclass(frozen=True)
class Token:
    kind: str
    text: str
    offset: int


_keywords = {"SELECT", "DISTINCT", "FROM", "INNER", "LEFT", "JOIN", "ON", "WHERE",
              "GROUP", "BY", "HAVING", "ORDER", "ASC", "DESC", "LIMIT", "OFFSET",
              "AS", "AND", "OR", "NOT", "IS", "NULL", "TRUE", "FALSE"}


def tokenize(source: str) -> list[Token]:
    out: list[Token] = []
    i = 0
    while i < len(source):
        if source[i].isspace():
            i += 1
            continue
        if source.startswith("--", i):
            i = source.find("\n", i)
            i = len(source) if i < 0 else i + 1
            continue
        start = i
        if source[i] == "'":
            i += 1
            chars: list[str] = []
            while i < len(source):
                if source[i] == "'":
                    if i + 1 < len(source) and source[i + 1] == "'":
                        chars.append("'"); i += 2; continue
                    i += 1
                    break
                chars.append(source[i]); i += 1
            else:
                raise LexError("unterminated string", start)
            out.append(Token("TEXT", "".join(chars), start)); continue
        m = re.match(r"(?:\d+\.\d*|\.\d+|\d+)(?:[eE][+-]?\d+)?", source[i:])
        if m:
            text = m.group(0); i += len(text)
            out.append(Token("FLOAT" if any(c in text for c in ".eE") else "INT", text, start)); continue
        m = re.match(r"[A-Za-z_][A-Za-z0-9_]*", source[i:])
        if m:
            text = m.group(0); i += len(text)
            upper = text.upper()
            out.append(Token(upper if upper in _keywords else "IDENT", text, start)); continue
        pair = source[i:i + 2]
        if pair in {"<>", "<=", ">="}:
            out.append(Token(pair, pair, start)); i += 2; continue
        if source[i] in "=<>+-*/%(),.":
            out.append(Token(source[i], source[i], start)); i += 1; continue
        raise LexError(f"invalid character {source[i]!r}", i)
    out.append(Token("EOF", "", len(source)))
    return out
