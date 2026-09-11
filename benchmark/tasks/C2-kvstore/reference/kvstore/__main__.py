"""Command line interface: ``python -m kvstore ROOT COMMAND [ARGS]``."""

from __future__ import annotations

import argparse
import sys

from .compact import compact
from .errors import CorruptSegmentError
from .store import KVStore

__all__ = ["build_parser", "main"]

_USAGE_EXIT = 2
_CORRUPT_EXIT = 3


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="kvstore", allow_abbrev=False)
    parser.add_argument("root")
    parser.add_argument("--max-segment-bytes", type=int, default=4096)
    subs = parser.add_subparsers(dest="command", required=True)
    p_set = subs.add_parser("set", allow_abbrev=False)
    p_set.add_argument("key")
    p_set.add_argument("value")
    for name in ("get", "delete"):
        sub = subs.add_parser(name, allow_abbrev=False)
        sub.add_argument("key")
    subs.add_parser("list", allow_abbrev=False)
    subs.add_parser("compact", allow_abbrev=False)
    subs.add_parser("stats", allow_abbrev=False)
    return parser


def _run(args: argparse.Namespace, out: object) -> int:
    with KVStore(args.root, max_segment_bytes=args.max_segment_bytes) as store:
        if args.command == "set":
            store.set(args.key, args.value)
            return 0
        if args.command == "get":
            value = store.get(args.key)
            if value is None:
                return 1
            print(value, file=out)
            return 0
        if args.command == "delete":
            return 0 if store.delete(args.key) else 1
        if args.command == "list":
            for key in store.keys():
                print(key, file=out)
            return 0
        if args.command == "compact":
            result = compact(store)
            print(
                f"removed={result.segments_removed} written={result.records_written} "
                f"dropped={result.records_dropped} reclaimed={result.bytes_reclaimed}",
                file=out,
            )
            return 0
        stats = store.stats()
        print(
            f"live_keys={stats.live_keys} tombstones={stats.tombstones} "
            f"total_records={stats.total_records} dead_records={stats.dead_records} "
            f"segment_count={stats.segment_count} bytes_on_disk={stats.bytes_on_disk}",
            file=out,
        )
        return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return _USAGE_EXIT if exc.code else 0
    if args.max_segment_bytes < 16:
        print("max-segment-bytes must be >= 16", file=sys.stderr)
        return _USAGE_EXIT
    try:
        return _run(args, sys.stdout)
    except CorruptSegmentError as exc:
        print(str(exc), file=sys.stderr)
        return _CORRUPT_EXIT
    except (TypeError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return _USAGE_EXIT


if __name__ == "__main__":
    sys.exit(main())
