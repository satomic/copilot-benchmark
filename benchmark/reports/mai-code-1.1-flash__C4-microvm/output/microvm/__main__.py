import argparse
import sys

from .compiler import compile_source
from .disassembler import disassemble
from .errors import MicroVMError
from .serializer import dumps, loads
from .vm import execute


def _positive_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("--step-limit must be a positive integer") from exc
    if parsed <= 0:
        raise argparse.ArgumentTypeError("--step-limit must be a positive integer")
    return parsed


def _read_text(path: str) -> str:
    with open(path, "r", encoding="utf-8") as handle:
        return handle.read()


def _read_bytes(path: str) -> bytes:
    with open(path, "rb") as handle:
        return handle.read()


def _make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="microvm", allow_abbrev=False)
    subparsers = parser.add_subparsers(dest="command", required=True)
    run_parser = subparsers.add_parser("run")
    run_parser.add_argument("file")
    run_parser.add_argument("--optimize", action="store_true")
    run_parser.add_argument("--step-limit", type=_positive_int, default=100_000)
    build_parser = subparsers.add_parser("build")
    build_parser.add_argument("source")
    build_parser.add_argument("output")
    build_parser.add_argument("--optimize", action="store_true")
    exec_parser = subparsers.add_parser("exec")
    exec_parser.add_argument("file")
    exec_parser.add_argument("--step-limit", type=_positive_int, default=100_000)
    disasm_parser = subparsers.add_parser("disasm")
    disasm_parser.add_argument("file")
    return parser


def _run_command(args: argparse.Namespace) -> int:
    program = compile_source(_read_text(args.file), optimize=args.optimize)
    output = execute(program, step_limit=args.step_limit)
    for line in output:
        print(line)
    return 0


def _build_command(args: argparse.Namespace) -> int:
    program = compile_source(_read_text(args.source), optimize=args.optimize)
    with open(args.output, "wb") as handle:
        handle.write(dumps(program))
    return 0


def _exec_command(args: argparse.Namespace) -> int:
    program = loads(_read_bytes(args.file))
    output = execute(program, step_limit=args.step_limit)
    for line in output:
        print(line)
    return 0


def _disasm_command(args: argparse.Namespace) -> int:
    sys.stdout.write(disassemble(loads(_read_bytes(args.file))))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = _make_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return int(exc.code) if isinstance(exc.code, int) else 2
    try:
        if args.command == "run":
            return _run_command(args)
        if args.command == "build":
            return _build_command(args)
        if args.command == "exec":
            return _exec_command(args)
        if args.command == "disasm":
            return _disasm_command(args)
    except (ValueError, OSError) as exc:
        print(exc, file=sys.stderr)
        return 2
    except MicroVMError as exc:
        print(exc, file=sys.stderr)
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
