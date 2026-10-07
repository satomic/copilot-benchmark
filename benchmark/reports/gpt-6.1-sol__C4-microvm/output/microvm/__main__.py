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
        raise argparse.ArgumentTypeError("Must be a positive integer") from error
    if value <= 0:
        raise argparse.ArgumentTypeError("Must be a positive integer")
    return value


def _arguments() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="microvm")
    commands = parser.add_subparsers(dest="command", required=True)
    for command in ("run", "build", "exec", "disasm"):
        subparser = commands.add_parser(command)
        subparser.add_argument("file")
        if command == "build":
            subparser.add_argument("out")
        if command in ("run", "build"):
            subparser.add_argument("--optimize", action="store_true")
        if command in ("run", "exec"):
            subparser.add_argument("--step-limit", type=_positive_int, default=100_000)
    return parser


def _perform(args: argparse.Namespace) -> str:
    path = Path(args.file)
    if args.command in ("run", "build"):
        program = compile_source(path.read_text(encoding="utf-8"), optimize=args.optimize)
    else:
        program = loads(path.read_bytes())
    if args.command == "build":
        Path(args.out).write_bytes(dumps(program))
        return ""
    if args.command == "disasm":
        return disassemble(program)
    lines = execute(program, step_limit=args.step_limit)
    return "".join(line + "\n" for line in lines)


def main(argv: list[str] | None = None) -> int:
    try:
        args = _arguments().parse_args(argv)
    except SystemExit as error:
        return int(error.code) if isinstance(error.code, int) else 2
    try:
        output = _perform(args)
    except (OSError, UnicodeError) as error:
        print(str(error), file=sys.stderr)
        return 2
    except MicroVMError as error:
        print(str(error), file=sys.stderr)
        return 3
    sys.stdout.write(output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
