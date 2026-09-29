"""CLI entry point for kvstore, runnable as ``python -m kvstore``."""

import argparse
import sys
from typing import Optional

from kvstore.store import KVStore
from kvstore.errors import CorruptSegmentError, KVStoreError


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="kvstore",
        description="Append-only key-value store",
    )
    parser.add_argument(
        "--max-segment-bytes",
        type=int,
        default=4096,
        help="Maximum segment file size in bytes (default: 4096)",
    )
    parser.add_argument("root", help="Store root directory")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("list", help="List live keys")
    subparsers.add_parser("stats", help="Show store statistics")
    subparsers.add_parser("compact", help="Compact the store")

    set_parser = subparsers.add_parser("set", help="Set a key-value pair")
    set_parser.add_argument("key", help="Key")
    set_parser.add_argument("value", help="Value")

    get_parser = subparsers.add_parser("get", help="Get a value by key")
    get_parser.add_argument("key", help="Key")

    del_parser = subparsers.add_parser("delete", help="Delete a key")
    del_parser.add_argument("key", help="Key")

    args = parser.parse_args(argv)

    if args.max_segment_bytes is not None and (
        not isinstance(args.max_segment_bytes, int) or args.max_segment_bytes <= 0
    ):
        print(
            "error: --max-segment-bytes must be a positive integer",
            file=sys.stderr,
        )
        return 2

    try:
        store = KVStore(args.root, max_segment_bytes=args.max_segment_bytes)
    except CorruptSegmentError as e:
        print(f"error: {e}", file=sys.stderr)
        return 3
    except KVStoreError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    try:
        return _run_command(store, args)
    finally:
        store.close()


def _run_command(store: KVStore, args: argparse.Namespace) -> int:
    command = args.command
    try:
        if command == "set":
            store.set(args.key, args.value)
            return 0
        elif command == "get":
            val = store.get(args.key)
            if val is None:
                return 1
            print(val)
            return 0
        elif command == "delete":
            result = store.delete(args.key)
            return 0 if result else 1
        elif command == "list":
            for key in store.keys():
                print(key)
            return 0
        elif command == "stats":
            s = store.stats()
            print(
                f"live_keys={s.live_keys} tombstones={s.tombstones} "
                f"total_records={s.total_records} dead_records={s.dead_records} "
                f"segment_count={s.segment_count} bytes_on_disk={s.bytes_on_disk}"
            )
            return 0
        elif command == "compact":
            from kvstore.compact import compact as do_compact

            result = do_compact(store)
            print(
                f"removed={result.segments_removed} "
                f"written={result.records_written} "
                f"dropped={result.records_dropped} "
                f"reclaimed={result.bytes_reclaimed}"
            )
            return 0
        else:
            print(f"error: unknown command: {command}", file=sys.stderr)
            return 2
    except (TypeError, ValueError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    except CorruptSegmentError as e:
        print(f"error: {e}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    sys.exit(main())