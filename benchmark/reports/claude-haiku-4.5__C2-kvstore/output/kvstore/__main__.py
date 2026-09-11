import sys
import argparse
from .store import KVStore
from .compact import compact
from .errors import CorruptSegmentError


def _create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="kvstore")
    parser.add_argument("--max-segment-bytes", type=int, default=4096)
    parser.add_argument("root")
    
    subparsers = parser.add_subparsers(dest="command", required=True)
    
    set_parser = subparsers.add_parser("set")
    set_parser.add_argument("key")
    set_parser.add_argument("value")
    
    get_parser = subparsers.add_parser("get")
    get_parser.add_argument("key")
    
    delete_parser = subparsers.add_parser("delete")
    delete_parser.add_argument("key")
    
    subparsers.add_parser("list")
    subparsers.add_parser("stats")
    subparsers.add_parser("compact")
    
    return parser


def _execute_command(store: KVStore, args: argparse.Namespace) -> int:
    if args.command == "set":
        store.set(args.key, args.value)
        return 0
    elif args.command == "get":
        result = store.get(args.key)
        if result is not None:
            print(result)
            return 0
        return 1
    elif args.command == "delete":
        return 0 if store.delete(args.key) else 1
    elif args.command == "list":
        for key in store.keys():
            print(key)
        return 0
    elif args.command == "stats":
        s = store.stats()
        print(f"live_keys={s.live_keys} tombstones={s.tombstones} "
              f"total_records={s.total_records} dead_records={s.dead_records} "
              f"segment_count={s.segment_count} bytes_on_disk={s.bytes_on_disk}")
        return 0
    elif args.command == "compact":
        r = compact(store)
        print(f"removed={r.segments_removed} written={r.records_written} "
              f"dropped={r.records_dropped} reclaimed={r.bytes_reclaimed}")
        return 0
    return 2


def main(argv: list[str] | None = None) -> int:
    parser = _create_parser()
    
    try:
        args = parser.parse_args(argv)
    except SystemExit as e:
        return e.code or 2
    
    try:
        max_seg = args.max_segment_bytes
        if not isinstance(max_seg, int) or max_seg < 16:
            print("Error: --max-segment-bytes must be an integer >= 16", 
                  file=sys.stderr)
            return 2
    except (ValueError, AttributeError):
        print("Error: --max-segment-bytes must be an integer >= 16", 
              file=sys.stderr)
        return 2
    
    try:
        store = KVStore(args.root, max_segment_bytes=max_seg)
    except (ValueError, TypeError) as e:
        print(f"Error: {e}", file=sys.stderr)
        return 2
    except CorruptSegmentError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 3
    
    try:
        return _execute_command(store, args)
    except (TypeError, ValueError) as e:
        print(f"Error: {e}", file=sys.stderr)
        return 2
    except CorruptSegmentError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 3
    finally:
        store.close()


if __name__ == "__main__":
    sys.exit(main())
