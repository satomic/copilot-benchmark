"""Command line interface: ``python -m kvstore ROOT COMMAND [ARGS...]``."""

from __future__ import annotations

import argparse
import sys

from .compact import compact
from .errors import CorruptSegmentError
from .store import KVStore

__all__ = ["main", "build_parser"]


def _positive_int(text: str) -> int:
    try:
        value = int(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{text!r} is not an integer") from None
    if value <= 0:
        raise argparse.ArgumentTypeError(f"{text!r} is not a positive integer")
    return value


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser for the CLI."""
    parser = argparse.ArgumentParser(prog="kvstore", description="Append-only KV store")
    parser.add_argument("root", help="store directory")
    parser.add_argument(
        "--max-segment-bytes", type=_positive_int, default=4096, dest="max_segment_bytes"
    )
    subs = parser.add_subparsers(dest="command", required=True)
    p_set = subs.add_parser("set", help="store a key/value pair")
    p_set.add_argument("key")
    p_set.add_argument("value")
    p_get = subs.add_parser("get", help="look a key up")
    p_get.add_argument("key")
    p_delete = subs.add_parser("delete", help="delete a key")
    p_delete.add_argument("key")
    subs.add_parser("list", help="list live keys")
    subs.add_parser("compact", help="compact the store")
    subs.add_parser("stats", help="print statistics")
    return parser


def _run(args: argparse.Namespace) -> int:
    """Execute one command against the store. Returns the exit code."""
    stream = sys.stdout
    with KVStore(args.root, max_segment_bytes=args.max_segment_bytes) as store:
        if args.command == "set":
            store.set(args.key, args.value)
            return 0
        if args.command == "get":
            value = store.get(args.key)
            if value is None:
                return 1
            stream.write(value + "\n")
            return 0
        if args.command == "delete":
            return 0 if store.delete(args.key) else 1
        if args.command == "list":
            for key in store.keys():
                stream.write(key + "\n")
            return 0
        if args.command == "compact":
            result = compact(store)
            stream.write(
                f"removed={result.segments_removed} "
                f"written={result.records_written} "
                f"dropped={result.records_dropped} "
                f"reclaimed={result.bytes_reclaimed}\n"
            )
            return 0
        stats = store.stats()
        stream.write(
            f"live_keys={stats.live_keys} tombstones={stats.tombstones} "
            f"total_records={stats.total_records} dead_records={stats.dead_records} "
            f"segment_count={stats.segment_count} "
            f"bytes_on_disk={stats.bytes_on_disk}\n"
        )
        return 0


def main(argv: list[str] | None = None) -> int:
    """Entry point. Returns the process exit code."""
    parser = build_parser()
    try:
        args = parser.parse_args(sys.argv[1:] if argv is None else argv)
    except SystemExit as exc:
        return 2 if exc.code else int(exc.code or 0)
    try:
        return _run(args)
    except CorruptSegmentError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 3
    except (ValueError, TypeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
