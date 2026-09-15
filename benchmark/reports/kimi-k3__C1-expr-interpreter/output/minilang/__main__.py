"""REPL for minilang, runnable as ``python -m minilang``.

Reads one line at a time from stdin. No prompt, no banner, no summary.
"""

import re
import sys

from . import evaluate
from .builtins import format_number
from .errors import MiniLangError

# "<ident> = <expr>" where the '=' is a single one, not part of '=='.
_ASSIGN_RE = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=(?!=)")


def _escape_string(value):
    return (
        value.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\t", "\\t")
        .replace("\r", "\\r")
    )


def format_value(value):
    if type(value) is bool:
        return "true" if value else "false"
    if type(value) is float:
        return format_number(value)
    return '"' + _escape_string(value) + '"'


def main():
    env = {}
    for raw_line in sys.stdin:
        line = raw_line.strip()
        if not line:
            continue
        if line == ":quit":
            return 0
        if line == ":vars":
            for name in sorted(env):
                print(f"{name} = {format_value(env[name])}")
            continue
        match = _ASSIGN_RE.match(raw_line)
        if match:
            name = match.group(1)
            expr = raw_line[match.end() :]
            try:
                value = evaluate(expr, env)
            except MiniLangError as exc:
                print(f"error: {exc}")
                continue
            # Store only on success, so failures leave env unchanged.
            env[name] = value
            continue
        try:
            print(format_value(evaluate(raw_line, env)))
        except MiniLangError as exc:
            print(f"error: {exc}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
