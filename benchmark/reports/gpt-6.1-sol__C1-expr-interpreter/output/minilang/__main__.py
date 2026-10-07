import re
import sys

from .builtins import format_value
from .errors import MiniLangError
from .evaluator import evaluate
from .lexer import KEYWORDS


ASSIGNMENT = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=(?!=)(.*)$", re.DOTALL)


def main() -> int:
    env = {}
    for line in sys.stdin:
        command = line.strip()
        if not command:
            continue
        if command == ":quit":
            return 0
        if command == ":vars":
            for name in sorted(env):
                print(f"{name} = {format_value(env[name])}")
            continue
        try:
            assignment = ASSIGNMENT.match(line)
            # Reserved keywords are not identifiers, including assignment targets.
            if assignment is not None and assignment[1] not in KEYWORDS:
                value = evaluate(assignment[2], env)
                env[assignment[1]] = value
            else:
                print(format_value(evaluate(line, env)))
        except MiniLangError as error:
            print(f"error: {error}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
