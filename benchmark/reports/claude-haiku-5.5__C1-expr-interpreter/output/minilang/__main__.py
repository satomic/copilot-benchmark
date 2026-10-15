"""REPL: ``python -m minilang``. Reads one line at a time from stdin."""

import re
import sys

from .builtins import format_value
from .errors import MiniLangError
from .evaluator import evaluate
from .lexer import KEYWORDS

_ASSIGN = re.compile(r"\s*([A-Za-z_][A-Za-z0-9_]*)\s*=(?!=)(.*)\Z", re.DOTALL)


def main():
    env = {}
    for raw in sys.stdin:
        line = raw.strip()
        if not line:
            continue
        if line == ":quit":
            return 0
        if line == ":vars":
            for name in sorted(env):
                print(f"{name} = {format_value(env[name])}")
            continue
        try:
            match = _ASSIGN.match(line)
            if match and match.group(1) not in KEYWORDS:
                env[match.group(1)] = evaluate(match.group(2), env)
            else:
                print(format_value(evaluate(line, env)))
        except MiniLangError as exc:
            print(f"error: {exc}")
    return 0


if __name__ == "__main__":
    for stream in (sys.stdin, sys.stdout):
        stream.reconfigure(encoding="utf-8")
    sys.exit(main())
