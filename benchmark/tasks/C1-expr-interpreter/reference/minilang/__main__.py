"""Line-oriented REPL: `python -m minilang`."""

from __future__ import annotations

import re
import sys

from .builtins import format_value
from .errors import MiniLangError
from .evaluator import evaluate

_ASSIGNMENT_RE = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=(?!=)(.*)$", re.DOTALL)


def main(argv: list[str] | None = None) -> int:
    env: dict[str, object] = {}
    for raw in sys.stdin:
        line = raw.rstrip("\n").rstrip("\r")
        if not line.strip():
            continue

        command = line.strip()
        if command == ":quit":
            return 0
        if command == ":vars":
            for name in sorted(env):
                print(f"{name} = {format_value(env[name])}")
            continue

        assignment = _ASSIGNMENT_RE.match(line)
        try:
            if assignment is not None:
                env[assignment.group(1)] = evaluate(assignment.group(2), env)
            else:
                print(format_value(evaluate(line, env)))
        except MiniLangError as exc:
            print(f"error: {exc}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
