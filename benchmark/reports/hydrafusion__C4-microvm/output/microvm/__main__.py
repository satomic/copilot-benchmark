import argparse
from pathlib import Path
import sys

from .compiler import compile_source
from .disassembler import disassemble
from .errors import MicroVMError
from .serializer import dumps, loads
from .vm import execute


class _UsageError(Exception):
    pass


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise _UsageError(message)


def _positive_int(text: str) -> int:
    try:
        value = int(text)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be a positive integer") from exc
    if value <= 0:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return value


def _argument_parser() -> argparse.ArgumentParser:
    parser = _Parser(prog="python -m microvm")
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run")
    run.add_argument("file")
    run.add_argument("--optimize", action="store_true")
    run.add_argument("--step-limit", type=_positive_int, default=100_000)
    build = commands.add_parser("build")
    build.add_argument("file")
    build.add_argument("out")
    build.add_argument("--optimize", action="store_true")
    execute_parser = commands.add_parser("exec")
    execute_parser.add_argument("file")
    execute_parser.add_argument("--step-limit", type=_positive_int, default=100_000)
    disasm = commands.add_parser("disasm")
    disasm.add_argument("file")
    return parser


def _read_text(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


def _read_bytes(path: str) -> bytes:
    return Path(path).read_bytes()


def _run(args: argparse.Namespace) -> str:
    program = compile_source(_read_text(args.file), optimize=args.optimize)
    return "".join(line + "\n" for line in execute(program, step_limit=args.step_limit))


def _exec(args: argparse.Namespace) -> str:
    program = loads(_read_bytes(args.file))
    return "".join(line + "\n" for line in execute(program, step_limit=args.step_limit))


def _dispatch(args: argparse.Namespace) -> str:
    if args.command == "run":
        return _run(args)
    if args.command == "build":
        program = compile_source(_read_text(args.file), optimize=args.optimize)
        Path(args.out).write_bytes(dumps(program))
        return ""
    if args.command == "exec":
        return _exec(args)
    return disassemble(loads(_read_bytes(args.file)))


def main(argv: list[str] | None = None) -> int:
    try:
        args = _argument_parser().parse_args(argv)
        output = _dispatch(args)
    except _UsageError as exc:
        print(f"usage error: {exc}", file=sys.stderr)
        return 2
    except (OSError, UnicodeError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except MicroVMError as exc:
        print(str(exc), file=sys.stderr)
        return 3
    sys.stdout.write(output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
