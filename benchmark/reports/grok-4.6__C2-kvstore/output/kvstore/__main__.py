"""CLI: python -m kvstore ROOT COMMAND [ARGS...]"""

from __future__ import annotations

import argparse
import sys

from kvstore.compact import compact
from kvstore.errors import CorruptSegmentError
from kvstore.store import KVStore


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        code = exc.code
        if code in (0, None):
            return 0
        return int(code)
    try:
        return _run(args)
    except CorruptSegmentError as exc:
        print(str(exc), file=sys.stderr)
        return 3
    except (ValueError, TypeError) as exc:
        print(str(exc), file=sys.stderr)
        return 2


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="kvstore")
    parser.add_argument("--max-segment-bytes", type=_positive_int, default=4096)
    parser.add_argument("root")
    sub = parser.add_subparsers(dest="command", required=True)
    p_set = sub.add_parser("set")
    p_set.add_argument("key")
    p_set.add_argument("value")
    p_get = sub.add_parser("get")
    p_get.add_argument("key")
    p_del = sub.add_parser("delete")
    p_del.add_argument("key")
    sub.add_parser("list")
    sub.add_parser("compact")
    sub.add_parser("stats")
    return parser


def _positive_int(text: str) -> int:
    try:
        value = int(text)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("max-segment-bytes must be a positive integer") from exc
    if value <= 0:
        raise argparse.ArgumentTypeError("max-segment-bytes must be a positive integer")
    return value


def _run(args: argparse.Namespace) -> int:
    with KVStore(args.root, max_segment_bytes=args.max_segment_bytes) as store:
        command = args.command
        if command == "set":
            store.set(args.key, args.value)
            return 0
        if command == "get":
            value = store.get(args.key)
            if value is None:
                return 1
            sys.stdout.write(value + "\n")
            return 0
        if command == "delete":
            return 0 if store.delete(args.key) else 1
        if command == "list":
            for key in store.keys():
                sys.stdout.write(key + "\n")
            return 0
        if command == "compact":
            result = compact(store)
            line = (
                f"removed={result.segments_removed} written={result.records_written} "
                f"dropped={result.records_dropped} reclaimed={result.bytes_reclaimed}\n"
            )
            sys.stdout.write(line)
            return 0
        if command == "stats":
            s = store.stats()
            sys.stdout.write(
                f"live_keys={s.live_keys} tombstones={s.tombstones} "
                f"total_records={s.total_records} dead_records={s.dead_records} "
                f"segment_count={s.segment_count} bytes_on_disk={s.bytes_on_disk}\n"
            )
            return 0
        return 2


if __name__ == "__main__":
    sys.exit(main())
