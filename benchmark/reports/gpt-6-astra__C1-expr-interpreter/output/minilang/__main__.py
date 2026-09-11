import re
import sys

from .builtins import Value, format_value
from .errors import MiniLangError, ParseError
from .evaluator import evaluate
from .lexer import KEYWORDS


_ASSIGNMENT = re.compile(r"([A-Za-z_][A-Za-z0-9_]*)\s*=(?!=)")


def main() -> int:
    env: dict[str, Value] = {}
    for line in sys.stdin:
        source = line.strip()
        if not source:
            continue
        if source == ":quit":
            return 0
        try:
            if source == ":vars":
                for name in sorted(env):
                    print(f"{name} = {format_value(env[name])}")
                continue
            assignment = _ASSIGNMENT.match(source)
            if assignment is not None:
                name = assignment.group(1)
                if name in KEYWORDS:
                    raise ParseError("expected identifier", assignment.start(1))
                value = evaluate(source[assignment.end():], env)
                env[name] = value
            else:
                print(format_value(evaluate(source, env)))
        except MiniLangError as error:
            print(f"error: {error}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
