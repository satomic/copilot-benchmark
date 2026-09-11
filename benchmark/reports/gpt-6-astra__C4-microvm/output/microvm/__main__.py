from __future__ import annotations

import argparse
from pathlib import Path
import sys

from .compiler import compile_source
from .disassembler import disassemble
from .errors import MicroVMError
from .serializer import dumps, loads
from .vm import execute


def _positive_int(text: str) -> int:
    try:
        value = int(text)
    except ValueError as error:
        raise argparse.ArgumentTypeError("step limit must be a positive integer") from error
    if value <= 0:
        raise argparse.ArgumentTypeError("step limit must be a positive integer")
    return value


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="microvm")
    subcommands = parser.add_subparsers(dest="command", required=True)
    for name in ("run", "build", "exec", "disasm"):
        command = subcommands.add_parser(name)
        command.add_argument("file", type=Path)
        if name in ("run", "build"):
            command.add_argument("--optimize", action="store_true")
        if name in ("run", "exec"):
            command.add_argument("--step-limit", type=_positive_int, default=100_000)
        if name == "build":
            command.add_argument("out", type=Path)
    return parser


def _dispatch(args: argparse.Namespace) -> str:
    if args.command in ("run", "build"):
        source = args.file.read_text(encoding="utf-8")
        program = compile_source(source, optimize=args.optimize)
    else:
        program = loads(args.file.read_bytes())
    if args.command == "build":
        data = dumps(program)
        args.out.write_bytes(data)
        return ""
    if args.command == "disasm":
        return disassemble(program)
    lines = execute(program, step_limit=args.step_limit)
    return "".join(line + "\n" for line in lines)


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as error:
        return int(error.code)
    try:
        output = _dispatch(args)
    except (OSError, UnicodeError) as error:
        print(f"microvm: {error}", file=sys.stderr)
        return 2
    except MicroVMError as error:
        print(f"microvm: {error}", file=sys.stderr)
        return 3
    sys.stdout.write(output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
