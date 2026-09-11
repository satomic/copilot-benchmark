"""REPL for minilang: ``python -m minilang``."""

import re
import sys

from .builtins import format_value
from .errors import MiniLangError
from .evaluator import evaluate
from .lexer import KEYWORDS

# Assignments are recognised on the raw line, before lexing, because a lone
# `=` is a LexError in the language itself.
_ASSIGNMENT_RE = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=(?!=)(.*)$", re.DOTALL)


def run_line(line, env, out):
    """Handle one REPL input line. Returns False when the REPL should stop."""
    stripped = line.strip()
    if not stripped:
        return True

    if stripped == ":quit":
        return False

    if stripped == ":vars":
        for name in sorted(env):
            print(f"{name} = {format_value(env[name])}", file=out)
        return True

    match = _ASSIGNMENT_RE.match(line)
    if match is not None and match.group(1) not in KEYWORDS:
        name, expression = match.group(1), match.group(2)
        try:
            value = evaluate(expression, env)
        except MiniLangError as error:
            print(f"error: {error}", file=out)
        else:
            env[name] = value
        return True

    try:
        value = evaluate(line, env)
    except MiniLangError as error:
        print(f"error: {error}", file=out)
    else:
        print(format_value(value), file=out)
    return True


def main(argv=None):
    env = {}
    for line in sys.stdin:
        if not run_line(line.rstrip("\n"), env, sys.stdout):
            break
    return 0


if __name__ == "__main__":
    sys.exit(main())
