import re
import sys

from .builtins import format_value
from .errors import MiniLangError
from .evaluator import evaluate


_ASSIGNMENT_RE = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=(?!=)\s*(.*)\s*$")


def main() -> int:
    env = {}
    for raw_line in sys.stdin:
        line = raw_line.rstrip("\r\n")
        stripped = line.strip()
        if not stripped:
            continue
        if stripped == ":quit":
            return 0
        if stripped == ":vars":
            if not env:
                continue
            for name in sorted(env):
                print(f"{name} = {format_value(env[name])}")
            continue

        match = _ASSIGNMENT_RE.match(line)
        if match:
            name, expr_src = match.groups()
            try:
                value = evaluate(expr_src, env)
            except MiniLangError as exc:
                print(f"error: {exc}")
                continue
            env[name] = value
            continue

        try:
            value = evaluate(line, env)
        except MiniLangError as exc:
            print(f"error: {exc}")
            continue
        print(format_value(value))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
