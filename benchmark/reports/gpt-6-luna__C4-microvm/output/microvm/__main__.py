import argparse
import sys
from pathlib import Path

from .compiler import compile_source
from .disassembler import disassemble
from .errors import MicroVMError
from .serializer import dumps, loads
from .vm import execute


def main(argv: list[str] | None = None) -> int:
    parser = _argument_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return int(exc.code)
    try:
        _run_command(args)
        return 0
    except MicroVMError as exc:
        print(str(exc), file=sys.stderr)
        return 3
    except (OSError, UnicodeError) as exc:
        print(str(exc), file=sys.stderr)
        return 2


def _argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m microvm")
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run")
    run.add_argument("file")
    run.add_argument("--optimize", action="store_true")
    run.add_argument("--step-limit", type=_positive, default=100_000)
    build = commands.add_parser("build")
    build.add_argument("file")
    build.add_argument("out")
    build.add_argument("--optimize", action="store_true")
    execute_cmd = commands.add_parser("exec")
    execute_cmd.add_argument("file")
    execute_cmd.add_argument("--step-limit", type=_positive, default=100_000)
    commands.add_parser("disasm").add_argument("file")
    return parser


def _positive(value: str) -> int:
    try:
        number = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be a positive integer") from exc
    if number <= 0:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return number


def _run_command(args: argparse.Namespace) -> None:
    if args.command in {"run", "build"}:
        source = Path(args.file).read_text(encoding="utf-8")
        program = compile_source(source, optimize=args.optimize)
        if args.command == "build":
            Path(args.out).write_bytes(dumps(program))
            return
        _print_lines(execute(program, step_limit=args.step_limit))
    elif args.command == "exec":
        program = loads(Path(args.file).read_bytes())
        _print_lines(execute(program, step_limit=args.step_limit))
    else:
        result = disassemble(loads(Path(args.file).read_bytes()))
        sys.stdout.write(result)


def _print_lines(lines: list[str]) -> None:
    for line in lines:
        print(line)


if __name__ == "__main__":
    sys.exit(main())
