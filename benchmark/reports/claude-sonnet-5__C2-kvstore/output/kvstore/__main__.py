"""Command-line interface for kvstore: python -m kvstore ROOT COMMAND [ARGS...]"""

from __future__ import annotations

import argparse
import sys

from .compact import compact
from .errors import CorruptSegmentError
from .store import KVStore


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="kvstore")
    parser.add_argument("root", help="path to the store root directory")
    parser.add_argument("--max-segment-bytes", type=int, default=4096)
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


def _run(args: argparse.Namespace) -> int:
    store = KVStore(args.root, max_segment_bytes=args.max_segment_bytes)
    try:
        if args.command == "set":
            store.set(args.key, args.value)
            return 0
        if args.command == "get":
            value = store.get(args.key)
            if value is None:
                return 1
            print(value)
            return 0
        if args.command == "delete":
            ok = store.delete(args.key)
            return 0 if ok else 1
        if args.command == "list":
            for key in store.keys():
                print(key)
            return 0
        if args.command == "compact":
            result = compact(store)
            print(
                f"removed={result.segments_removed} written={result.records_written} "
                f"dropped={result.records_dropped} reclaimed={result.bytes_reclaimed}"
            )
            return 0
        if args.command == "stats":
            s = store.stats()
            print(
                f"live_keys={s.live_keys} tombstones={s.tombstones} "
                f"total_records={s.total_records} dead_records={s.dead_records} "
                f"segment_count={s.segment_count} bytes_on_disk={s.bytes_on_disk}"
            )
            return 0
        return 2
    finally:
        store.close()


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        code = exc.code
        return code if isinstance(code, int) else 2

    try:
        return _run(args)
    except CorruptSegmentError as exc:
        print(str(exc), file=sys.stderr)
        return 3
    except (ValueError, TypeError) as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
