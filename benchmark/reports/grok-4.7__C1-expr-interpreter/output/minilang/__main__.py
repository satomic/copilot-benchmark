"""REPL. A single ``=`` is assignment syntax here only; the lexer rejects it.

Commands are recognized after stripping surrounding whitespace. ``\\r`` is
treated as whitespace so Windows line endings do not become tokens.
"""

import re
import sys

from minilang.builtins import format_value
from minilang.errors import MiniLangError
from minilang.evaluator import evaluate

_IDENT_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")
_KEYWORDS = frozenset({"true", "false", "and", "or", "not"})


def _split_assignment(line: str):
    """Return ``(name_text, expr_text)`` if the line has a top-level single ``=``."""
    index = 0
    length = len(line)
    while index < length:
        char = line[index]
        if char == "#":
            return None
        if char == '"':
            index += 1
            while index < length:
                if line[index] == "\\" and index + 1 < length:
                    index += 2
                    continue
                if line[index] == '"':
                    index += 1
                    break
                index += 1
            continue
        if char in "=!<>" and index + 1 < length and line[index + 1] == "=":
            index += 2
            continue
        if char == "=":
            return line[:index], line[index + 1 :]
        index += 1
    return None


def _handle_line(line: str, env: dict) -> None:
    stripped = line.strip()
    if stripped == "" or stripped == ":vars":
        if stripped == ":vars":
            for name in sorted(env):
                print(f"{name} = {format_value(env[name])}")
        return
    split = _split_assignment(line)
    if split is not None:
        left, right = split
        name = left.strip()
        if _IDENT_RE.fullmatch(name) and name not in _KEYWORDS:
            try:
                value = evaluate(right, env)
            except MiniLangError as exc:
                print(f"error: {exc}")
                return
            env[name] = value
            return
    try:
        value = evaluate(line, env)
    except MiniLangError as exc:
        print(f"error: {exc}")
        return
    print(format_value(value))


def main() -> int:
    env: dict = {}
    while True:
        line = sys.stdin.readline()
        if line == "":
            return 0
        if line.endswith("\n"):
            line = line[:-1]
        if line.endswith("\r"):
            line = line[:-1]
        if line.strip() == ":quit":
            return 0
        _handle_line(line, env)


if __name__ == "__main__":
    raise SystemExit(main())
