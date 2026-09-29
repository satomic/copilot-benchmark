"""Line-oriented REPL: ``python -m minilang``."""

import re
import sys

from .builtins import format_value
from .errors import MiniLangError
from .evaluator import evaluate
from .lexer import KEYWORDS

_ASSIGN_RE = re.compile(r"\s*([A-Za-z_][A-Za-z0-9_]*)\s*=(?!=)(.*)", re.DOTALL)


def run(stdin=sys.stdin, stdout=sys.stdout):
    env = {}
    for raw in stdin:
        line = raw.rstrip("\r\n")
        stripped = line.strip()
        if not stripped:
            continue
        if stripped == ":quit":
            return 0
        if stripped == ":vars":
            for name in sorted(env):
                print(f"{name} = {format_value(env[name])}", file=stdout)
            continue
        try:
            match = _ASSIGN_RE.fullmatch(line)
            if match:
                name, expr = match.group(1), match.group(2)
                if name in KEYWORDS:
                    raise MiniLangError(f"cannot assign to keyword: {name}")
                env[name] = evaluate(expr, env)
            else:
                print(format_value(evaluate(line, env)), file=stdout)
        except MiniLangError as exc:
            print(f"error: {exc}", file=stdout)
        stdout.flush()
    return 0


if __name__ == "__main__":
    sys.exit(run())
