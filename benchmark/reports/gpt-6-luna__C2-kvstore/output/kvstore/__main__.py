"""Command-line interface for ``python -m kvstore``."""

import argparse
import sys

from .compact import compact
from .errors import CorruptSegmentError
from .store import KVStore


def _positive_int(text: str) -> int:
    """Parse a positive integer suitable for the CLI option."""
    try:
        value = int(text)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be a positive integer") from exc
    if value <= 0:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return value


def _parser() -> argparse.ArgumentParser:
    """Create the command parser and subcommands."""
    parser = argparse.ArgumentParser(prog="python -m kvstore")
    parser.add_argument("--max-segment-bytes", type=_positive_int, default=4096)
    parser.add_argument("root")
    commands = parser.add_subparsers(dest="command", required=True)
    set_cmd = commands.add_parser("set")
    set_cmd.add_argument("key")
    set_cmd.add_argument("value")
    for name in ("get", "delete"):
        command = commands.add_parser(name)
        command.add_argument("key")
    commands.add_parser("list")
    commands.add_parser("compact")
    commands.add_parser("stats")
    return parser


def _run(args: argparse.Namespace) -> int:
    """Execute one parsed command and write its successful output."""
    with KVStore(args.root, max_segment_bytes=args.max_segment_bytes) as store:
        if args.command == "set":
            store.set(args.key, args.value)
        elif args.command == "get":
            value = store.get(args.key)
            if value is None:
                return 1
            sys.stdout.write(value + "\n")
        elif args.command == "delete":
            return 0 if store.delete(args.key) else 1
        elif args.command == "list":
            for key in store.keys():
                sys.stdout.write(key + "\n")
        elif args.command == "compact":
            result = compact(store)
            sys.stdout.write(
                f"removed={result.segments_removed} written={result.records_written} "
                f"dropped={result.records_dropped} reclaimed={result.bytes_reclaimed}\n"
            )
        elif args.command == "stats":
            stats = store.stats()
            fields = ("live_keys", "tombstones", "total_records", "dead_records",
                      "segment_count", "bytes_on_disk")
            sys.stdout.write(" ".join(f"{field}={getattr(stats, field)}" for field in fields) + "\n")
    return 0


def main(argv: list[str] | None = None) -> int:
    """Parse arguments, run the command, and map store errors to exit codes."""
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        return _run(args)
    except CorruptSegmentError as exc:
        print(str(exc), file=sys.stderr)
        return 3
    except (TypeError, ValueError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
