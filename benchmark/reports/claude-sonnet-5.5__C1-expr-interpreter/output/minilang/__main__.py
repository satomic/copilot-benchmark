import re
import sys

from .builtins import format_value
from .errors import MiniLangError
from .evaluator import evaluate
from .lexer import KEYWORDS

_ASSIGN = re.compile(r"\s*([A-Za-z_][A-Za-z0-9_]*)\s*=(?!=)(.*)", re.DOTALL)


def main():
    env = {}
    out = sys.stdout
    for raw in sys.stdin:
        line = raw.strip()
        if not line:
            continue
        if line == ":quit":
            return 0
        if line == ":vars":
            for name in sorted(env):
                out.write(f"{name} = {format_value(env[name])}\n")
            continue
        try:
            m = _ASSIGN.fullmatch(line)
            if m and m.group(1) not in KEYWORDS:
                env[m.group(1)] = evaluate(m.group(2), env)
            else:
                out.write(format_value(evaluate(line, env)) + "\n")
        except MiniLangError as e:
            out.write(f"error: {e}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
