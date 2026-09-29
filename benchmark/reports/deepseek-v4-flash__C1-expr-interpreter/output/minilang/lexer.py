import re
from minilang.errors import LexError


class Token:
    __slots__ = ("kind", "value", "position")

    def __init__(self, kind: str, value: object, position: int):
        self.kind = kind
        self.value = value
        self.position = position

    def __repr__(self):
        return f"Token({self.kind}, {self.value!r}, {self.position})"


# Token patterns, ordered by priority.
# NUMBER order:
#  1. decimal with exponent: 1.5e-4, .5e3
#  2. integer with exponent: 1e3, 2E+8
#  3. dot-prefixed decimal: .5
#  4. trailing dot (will be rejected): 1.
#  5. decimal without exponent: 1.5
#  6. plain integer: 123
TOKEN_PATTERNS: list[tuple[str, str]] = [
    ("COMMENT", r"#.*"),
    ("NUMBER",
     r"\d+\.\d*[eE][+-]?\d+|\.\d+[eE][+-]?\d+|\d+[eE][+-]?\d+"
     r"|\.\d+"
     r"|\d+\.(?=[^.\d]|\Z)"
     r"|\d+\.\d*"
     r"|\d+"),
    ("STRING", r'"(?:[^"\\\n]|\\(?:n|t|r|"|\\))*"'),
    ("KEYWORD", r"true|false|and|or|not"),
    ("IDENT", r"[A-Za-z_][A-Za-z0-9_]*"),
    # Multi-char ops MUST come before single-char; '.' is NOT a valid standalone op
    ("OP", r"==|!=|<=|>=|[-+*/%^()<>=,]"),
    ("WS", r"[ \t\n\r]+"),
]

_parts = []
for kind, pat in TOKEN_PATTERNS:
    _parts.append(f"(?P<{kind}>{pat})")
_combined_re = re.compile("|".join(_parts))


def tokenize(source: str) -> list:
    tokens: list[Token] = []
    pos = 0

    while pos < len(source):
        m = _combined_re.match(source, pos)
        if m is None:
            ch = source[pos]
            if ch == ".":
                raise LexError(f"unexpected character: {ch!r}", pos)
            raise LexError(f"unexpected character: {ch!r}", pos)

        kind = m.lastgroup
        text = m.group()
        start = pos
        pos = m.end()

        if kind == "WS" or kind == "COMMENT":
            continue

        if kind == "NUMBER":
            # Reject trailing dot
            if text.endswith("."):
                raise LexError("invalid number: trailing dot", start)
            tokens.append(Token("NUMBER", text, start))
        elif kind == "STRING":
            # Check for unterminated string (shouldn't happen with the regex,
            # but double-check newlines inside)
            s = text[1:-1]
            value = _unescape_string(s, start)
            tokens.append(Token("STRING", value, start))
        elif kind == "KEYWORD":
            tokens.append(Token("KEYWORD", text, start))
        elif kind == "IDENT":
            tokens.append(Token("IDENT", text, start))
        elif kind == "OP":
            # Single '=' that is not part of '==' is a LexError
            if text == "=":
                raise LexError("invalid character: '=' (use '==' for equality)", start)
            tokens.append(Token("OP", text, start))

    return tokens


def _unescape_string(s: str, pos: int) -> str:
    """Unescape a string literal, raising LexError on invalid escapes."""
    chars = []
    i = 0
    while i < len(s):
        if s[i] == "\\":
            if i + 1 >= len(s):
                raise LexError("unterminated string", pos)
            esc = s[i + 1]
            if esc == "n":
                chars.append("\n")
            elif esc == "t":
                chars.append("\t")
            elif esc == "r":
                chars.append("\r")
            elif esc == '"':
                chars.append('"')
            elif esc == "\\":
                chars.append("\\")
            else:
                raise LexError(f"invalid escape: \\{esc}", pos)
            i += 2
        else:
            chars.append(s[i])
            i += 1
    return "".join(chars)