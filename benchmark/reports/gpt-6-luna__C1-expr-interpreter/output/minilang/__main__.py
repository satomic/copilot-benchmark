import re
import sys

from . import evaluate
from .builtins import format_value
from .errors import MiniLangError


_ASSIGNMENT = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=(?!=)(.*)$")


def main() -> int:
    env = {}
    for line in sys.stdin:
        stripped = line.strip()
        if not stripped:
            continue
        if stripped == ":quit":
            return 0
        if stripped == ":vars":
            for name in sorted(env):
                print(f"{name} = {format_value(env[name])}")
            continue
        assignment = _ASSIGNMENT.match(line)
        try:
            if assignment:
                value = evaluate(assignment.group(2), env)
                env[assignment.group(1)] = value
            else:
                print(format_value(evaluate(line, env)))
        except MiniLangError as error:
            print(f"error: {error}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
