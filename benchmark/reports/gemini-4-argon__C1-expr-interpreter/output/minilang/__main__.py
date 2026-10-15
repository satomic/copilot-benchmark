import re
import sys
from .builtins import format_repl_value
from .errors import MiniLangError
from .evaluator import evaluate
from .lexer import KEYWORDS

_ASSIGN_RE = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=(?!=)(.*)$")


def main() -> int:
    env: dict[str, object] = {}

    for raw_line in sys.stdin:
        line = raw_line.rstrip("\r\n")
        stripped = line.strip()

        if not stripped:
            continue

        if stripped == ":quit":
            return 0

        if stripped == ":vars":
            for name in sorted(env):
                print(f"{name} = {format_repl_value(env[name])}")
            continue

        match = _ASSIGN_RE.match(line)
        if match and match.group(1) not in KEYWORDS:
            var_name = match.group(1)
            expr_src = match.group(2)
            try:
                val = evaluate(expr_src, env)
            except MiniLangError as err:
                print(f"error: {err}")
            else:
                env[var_name] = val
            continue

        try:
            val = evaluate(line, env)
        except MiniLangError as err:
            print(f"error: {err}")
        else:
            print(format_repl_value(val))

    return 0


if __name__ == "__main__":
    sys.exit(main())
