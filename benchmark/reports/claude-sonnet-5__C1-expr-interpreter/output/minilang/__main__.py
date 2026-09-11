"""REPL for minilang: ``python -m minilang``."""

import re
import sys

from .errors import MiniLangError
from .evaluator import evaluate_ast, format_value
from .parser import parse

_ASSIGN_RE = re.compile(
    r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=(?!=)(.*)$", re.DOTALL
)


def main():
    env: dict = {}
    for raw_line in sys.stdin:
        line = raw_line.rstrip("\n")
        stripped = line.strip()

        if stripped == "":
            continue

        if stripped == ":quit":
            sys.exit(0)

        if stripped == ":vars":
            for name in sorted(env):
                print(f"{name} = {format_value(env[name])}")
            continue

        m = _ASSIGN_RE.match(line)
        if m:
            ident, expr_src = m.groups()
            try:
                ast = parse(expr_src)
                value = evaluate_ast(ast, env)
            except MiniLangError as e:
                print(f"error: {e}")
                continue
            env[ident] = value
            continue

        try:
            ast = parse(line)
            value = evaluate_ast(ast, env)
        except MiniLangError as e:
            print(f"error: {e}")
            continue
        print(format_value(value))

    sys.exit(0)


if __name__ == "__main__":
    main()
