"""Command line interface."""

import argparse
import sys

from .compiler import compile_source
from .disassembler import disassemble
from .errors import MicroVMError
from .serializer import dumps, loads
from .vm import execute


class _UsageError(Exception):
    pass


def _positive_int(text: str) -> int:
    try:
        value = int(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"not a positive integer: {text!r}") from None
    if value <= 0:
        raise argparse.ArgumentTypeError(f"not a positive integer: {text!r}")
    return value


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="microvm")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="compile and execute a source file")
    run.add_argument("file")
    run.add_argument("--optimize", action="store_true")
    run.add_argument("--step-limit", type=_positive_int, default=100_000)
    build = sub.add_parser("build", help="compile a source file to a binary")
    build.add_argument("file")
    build.add_argument("out")
    build.add_argument("--optimize", action="store_true")
    run_bin = sub.add_parser("exec", help="execute a binary file")
    run_bin.add_argument("file")
    run_bin.add_argument("--step-limit", type=_positive_int, default=100_000)
    disasm = sub.add_parser("disasm", help="disassemble a binary file")
    disasm.add_argument("file")
    return parser


def _read_bytes(path: str) -> bytes:
    try:
        with open(path, "rb") as handle:
            return handle.read()
    except OSError as exc:
        raise _UsageError(f"cannot read {path}: {exc}") from None


def _read_source(path: str) -> str:
    try:
        return _read_bytes(path).decode("utf-8")
    except UnicodeDecodeError:
        raise _UsageError(f"cannot decode {path} as UTF-8") from None


def _dispatch(args: argparse.Namespace) -> str:
    """Run a command and return the text to print on success."""
    if args.command == "run":
        program = compile_source(_read_source(args.file), optimize=args.optimize)
        return "".join(line + "\n" for line in execute(program, step_limit=args.step_limit))
    if args.command == "build":
        data = dumps(compile_source(_read_source(args.file), optimize=args.optimize))
        try:
            with open(args.out, "wb") as handle:
                handle.write(data)
        except OSError as exc:
            raise _UsageError(f"cannot write {args.out}: {exc}") from None
        return ""
    program = loads(_read_bytes(args.file))
    if args.command == "exec":
        return "".join(line + "\n" for line in execute(program, step_limit=args.step_limit))
    return disassemble(program)


def main(argv: list[str] | None = None) -> int:
    try:
        args = _build_parser().parse_args(argv)
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else 2
    try:
        text = _dispatch(args)
    except _UsageError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except MicroVMError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 3
    sys.stdout.write(text)
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
