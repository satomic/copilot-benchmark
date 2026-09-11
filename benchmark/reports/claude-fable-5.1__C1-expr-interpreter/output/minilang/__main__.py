"""REPL for minilang, runnable as ``python -m minilang``."""

import re
import sys

from .builtins import format_value
from .errors import MiniLangError
from .evaluator import evaluate
from .lexer import KEYWORDS

# `<ident> = <expr>` where the `=` is not part of `==`.
_ASSIGNMENT = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=(?!=)(.*)$", re.DOTALL)


def _handle_line(line: str, env: dict, out) -> bool:
    """Process one input line. Returns False when the REPL should stop."""
    stripped = line.strip()
    if not stripped:
        return True
    if stripped == ":quit":
        return False
    if stripped == ":vars":
        for name in sorted(env):
            out.write(f"{name} = {format_value(env[name])}\n")
        return True

    match = _ASSIGNMENT.match(line)
    # Keywords are not identifiers, so `true = 1` falls through to expression
    # evaluation (and reports the stray `=` as an error).
    if match and match.group(1) not in KEYWORDS:
        name, expr = match.group(1), match.group(2)
        try:
            env[name] = evaluate(expr, env)
        except MiniLangError as exc:
            out.write(f"error: {exc}\n")
        return True

    try:
        out.write(format_value(evaluate(line, env)) + "\n")
    except MiniLangError as exc:
        out.write(f"error: {exc}\n")
    return True


def main(stdin=None, stdout=None) -> int:
    stdin = stdin if stdin is not None else sys.stdin
    stdout = stdout if stdout is not None else sys.stdout
    env: dict = {}
    for line in stdin:
        if not _handle_line(line, env, stdout):
            break
        stdout.flush()
    stdout.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
