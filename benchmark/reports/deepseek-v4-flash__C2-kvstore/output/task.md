# Task C2: `kvstore`, An Append-Only Key-Value Store

**Difficulty:** Complex

## Working agreement (read this first)

- This folder is the project root. Do not read or write anything outside it.
- Python 3.11 and `pytest` are available. Use the **standard library only**. Do not install
  any third-party package and do not access the network.
- You may use `zlib.crc32`, `struct`, `os`, `pathlib`, `argparse`, `dataclasses`, `typing`.
  Do not use `pickle`, `shelve`, `dbm`, `sqlite3`, `json`, or any other serialisation
  library for the on-disk format: the byte layout below must be produced by your own code.
- Create **exactly** the files listed under *Deliverables*. Do not add extra files
  (no `README.md`, no `requirements.txt`, no `pyproject.toml`, no scratch files).
- Do not ask clarifying questions. If something is genuinely ambiguous, choose the most
  reasonable interpretation, implement it, and record the choice in a short code comment.
- When the deliverables satisfy the acceptance criteria, stop.

## Goal

Implement a durable key-value store built on append-only segment files: a binary record
codec, segment files, an in-memory index, crash recovery, compaction, and a CLI, plus a
test suite.

Both keys and values are `str`. The store survives being closed and reopened, and it
tolerates a process that was killed midway through a write.

## Deliverables

```
kvstore/__init__.py        # public surface, __all__
kvstore/errors.py          # exception hierarchy
kvstore/record.py          # encode_record / decode_record
kvstore/segment.py         # Segment: one append-only file
kvstore/index.py           # Index: key -> location
kvstore/store.py           # KVStore
kvstore/compact.py         # compact()
kvstore/__main__.py        # CLI, runnable as `python -m kvstore`
tests/test_kvstore.py      # your own test suite
```

No other files. `tests/` needs no `__init__.py`.

## 1. Record format

Every record is a 15-byte header followed by the key bytes and then the value bytes.
All integers are **big-endian unsigned**.

| offset | size | field | notes |
|---|---|---|---|
| 0 | 4 | `magic` | exactly `b"KVR1"` |
| 4 | 1 | `flags` | `0x00` = value present, `0x01` = tombstone. No other value is legal. |
| 5 | 2 | `key_len` | UTF-8 byte length of the key, `1..65535` |
| 7 | 4 | `value_len` | UTF-8 byte length of the value |
| 11 | 4 | `crc` | CRC32 (`zlib.crc32`) of `key_bytes + value_bytes` |
| 15 | `key_len` | `key_bytes` | UTF-8 |
| 15+`key_len` | `value_len` | `value_bytes` | UTF-8 |

Rules:

1. The total size of a record is `15 + key_len + value_len`.
2. The CRC covers **only the key bytes and the value bytes**, concatenated in that order.
   It does **not** cover the header.
3. A tombstone (`flags == 0x01`) always has `value_len == 0` and no value bytes.
4. `key_len` is never `0`.
5. An empty string is a perfectly valid **value**: `flags == 0x00` with `value_len == 0`.
   This is a different record from a tombstone even though both are 15 bytes long,
   and the store must treat them differently.

### 1.1 `record.py` API

```python
def encode_record(key: str, value: str | None) -> bytes
def decode_record(buf: bytes, offset: int = 0) -> tuple[str, str | None, int]
```

- `encode_record(key, value)` returns the complete record. `value=None` means a tombstone.
- `decode_record(buf, offset)` decodes the record starting at `buf[offset]` and returns
  `(key, value, total_size)`, where `value` is `None` for a tombstone and `total_size` is
  the number of bytes consumed.
- `decode_record` raises `IncompleteRecordError` when fewer bytes are available than the
  record needs (see section 3), and `CorruptRecordError` for anything else that is wrong:
  bad magic, unknown `flags`, `key_len == 0`, a tombstone with `value_len != 0`,
  a CRC mismatch, or key/value bytes that are not valid UTF-8.
- Both are checked in that order: structural problems before the CRC, and the CRC before
  UTF-8 decoding.

## 2. Segment files

- A segment file is named `<id>.seg` where `<id>` is the segment id **zero-padded to six
  digits**: `000001.seg`, `000002.seg`, ... Ids start at `1`.
- Segment files live directly in the store root. The store root is created if missing.
- Files in the root that do not match `^\d{6}\.seg$` are ignored completely, including
  during recovery. (A leftover `000003.seg.tmp` is therefore ignored.)

### 2.1 `segment.py` API

```python
class Segment:
    def __init__(self, path: pathlib.Path, seg_id: int) -> None
    @property
    def seg_id(self) -> int
    @property
    def size(self) -> int                       # current byte length of the file
    def append(self, blob: bytes) -> int        # returns the offset the blob was written at
    def scan(self) -> Iterator[tuple[str, str | None, int]]   # (key, value, offset)
    def close(self) -> None
```

- `append` writes at the end of the file and flushes so that a reopen sees the bytes.
- `scan` yields every record in ascending offset order.

## 3. Recovery: truncation versus corruption

This distinction is the heart of the task.

A process can be killed halfway through `append`, leaving a partially written record at the
**end** of a segment. That is normal and must be tolerated. Anything else is corruption and
must be reported.

1. **Truncated tail.** While scanning, if fewer than 15 bytes remain, or if the header is
   complete but fewer than `key_len + value_len` bytes follow it, the remaining bytes are a
   partial write. `scan` stops cleanly and yields nothing further. No error.
2. **Corruption.** A record with bad magic, unknown `flags`, `key_len == 0`, a tombstone
   with `value_len != 0`, a CRC mismatch, or non-UTF-8 key/value bytes is corruption.
   `scan` raises `CorruptSegmentError`.
   **This applies even when the bad record is the last one in the file.** A CRC mismatch is
   never treated as a truncated tail: the bytes are all there, they are simply wrong.
3. `CorruptSegmentError` carries the segment path and the byte offset of the bad record:
   attributes `path` (a `pathlib.Path`) and `offset` (an `int`). Its `str()` must contain
   the file name and the offset in decimal.

## 4. Index

### 4.1 `index.py` API

```python
@dataclasses.dataclass(frozen=True)
class Location:
    seg_id: int
    offset: int

class Index:
    def __init__(self) -> None
    def put(self, key: str, loc: Location, *, tombstone: bool) -> None
    def get(self, key: str) -> Location | None      # None if absent or tombstoned
    def live_keys(self) -> list[str]
    def tombstone_count(self) -> int
    def __len__(self) -> int                        # number of live keys
```

- `put` records the newest known record for `key`. A later `put` for the same key replaces
  the earlier one, whether or not either is a tombstone.
- `live_keys()` returns the keys whose newest record is **not** a tombstone, ordered by the
  position of that newest record: ascending `seg_id`, then ascending `offset`.
  Re-writing an existing key therefore moves it to the **end** of the list.
- `tombstone_count()` is the number of distinct keys whose newest record is a tombstone.

## 5. `KVStore`

### 5.1 API

```python
class KVStore:
    def __init__(self, root: str | os.PathLike, *, max_segment_bytes: int = 4096) -> None
    def set(self, key: str, value: str) -> None
    def get(self, key: str) -> str | None
    def delete(self, key: str) -> bool
    def keys(self) -> list[str]
    def stats(self) -> Stats
    def close(self) -> None
    def __enter__(self) -> "KVStore"
    def __exit__(self, *exc: object) -> None
```

### 5.2 Behaviour

1. `__init__` creates the root if needed, then recovers: it scans every `<id>.seg` in
   **ascending id order**, and within each segment in ascending offset order, feeding every
   record into the index. Later records win.
2. The **active segment** is the one with the highest id. If there are no segments, create
   `000001.seg`.
3. `set(key, value)` appends a value record and updates the index.
4. `get(key)` returns the value string, or `None` if the key is absent or its newest record
   is a tombstone. An empty-string value returns `""`, which is **not** `None`.
5. `delete(key)` appends a tombstone and returns `True` **only if the key is currently
   live**. If the key is absent or already tombstoned, `delete` returns `False` and
   **writes nothing at all**: the log must not grow for a no-op delete.
6. `keys()` returns `index.live_keys()`.
7. `close()` closes the open segment file. Using a closed store raises `ValueError`.
   `close()` is idempotent.

### 5.3 Type and value validation

Validation happens **before** anything is written.

1. `key` must be an instance of `str`; anything else, including `bytes`, raises `TypeError`.
   Do not decode `bytes` for the caller.
2. `value` must be an instance of `str` for `set`; anything else raises `TypeError`.
3. The **UTF-8 encoded byte length** of `key` must be in `1..65535`. Otherwise `ValueError`.
   Note that this is a limit on bytes, not on characters: a 40000-character string of CJK
   characters encodes to 120000 bytes and must be rejected.
4. `max_segment_bytes` must be an `int` greater than or equal to `16`, else `ValueError`.

### 5.4 Segment rollover

Before appending a record of size `n` to the active segment:

- If the active segment is **empty** (`size == 0`), append to it regardless of `n`.
  A single record larger than `max_segment_bytes` must still be stored.
- Otherwise, if `size + n > max_segment_bytes`, create a new segment with id
  `active.seg_id + 1` and append there. Note the comparison is strictly greater than:
  a record that makes the segment exactly `max_segment_bytes` long still fits.

### 5.5 `Stats`

`Stats` is a frozen dataclass (or `NamedTuple`) exported from `kvstore`, with these fields
in this order:

```python
live_keys: int        # keys whose newest record is a value
tombstones: int       # keys whose newest record is a tombstone
total_records: int    # every record on disk, across all segments
dead_records: int     # total_records - live_keys - tombstones
segment_count: int    # number of <id>.seg files
bytes_on_disk: int    # sum of the byte length of every <id>.seg file
```

`dead_records` counts records that have been superseded. The newest tombstone of a key is
**not** dead: it is still doing work, so it is counted by `tombstones` and excluded from
`dead_records`. `bytes_on_disk` includes any ignored truncated tail, because those bytes are
really on disk.

## 6. Compaction

### 6.1 `compact.py` API

```python
class CompactionResult(NamedTuple):
    segments_removed: int
    records_written: int
    records_dropped: int
    bytes_reclaimed: int

def compact(store: KVStore) -> CompactionResult
```

### 6.2 Behaviour

`compact` rewrites the whole store into one new segment holding exactly one record per live
key, then removes the old segments.

1. The new segment id is `max(existing ids) + 1`.
2. Records are written **in `store.keys()` order**, so compaction preserves the ordering
   that `keys()` reports.
3. Because every segment is being compacted, no older segment can survive to shadow a
   deletion, so tombstones are **dropped entirely**. Keys whose newest record is a
   tombstone do not appear in the new segment.
4. The new segment is written to `<newid>.seg.tmp` first and then moved into place with
   `os.replace`. Old segment files are deleted **only after** that move succeeds. If the
   process dies before the move, the store must still recover to its pre-compaction state,
   which is why the temporary name must not match `^\d{6}\.seg$`.
5. The new segment becomes the active segment. Writes after compaction append to it and
   obey rollover as usual.
6. The new segment is created even when it would be empty, so the store always has an
   active segment.
7. The store's index is rebuilt so that `keys()` order is unchanged and `get` still works.

Return value:

- `segments_removed`: how many old segment files were deleted.
- `records_written`: how many records the new segment contains.
- `records_dropped`: `total_records_before - records_written`.
- `bytes_reclaimed`: `bytes_on_disk_before - bytes_on_disk_after`.

## 7. CLI

`python -m kvstore ROOT COMMAND [ARGS...]`, implemented with `argparse` subcommands.

| command | behaviour | stdout | exit |
|---|---|---|---|
| `set KEY VALUE` | store the pair | nothing | 0 |
| `get KEY` | look up | the value plus `\n` | 0 |
| `get KEY` (absent) | look up | nothing | 1 |
| `delete KEY` | delete a live key | nothing | 0 |
| `delete KEY` (not live) | no-op | nothing | 1 |
| `list` | list live keys | one key per line, `keys()` order | 0 |
| `compact` | compact | `removed=A written=B dropped=C reclaimed=D` plus `\n` | 0 |
| `stats` | report | see below | 0 |

`stats` prints exactly one line, the six fields in `Stats` order, space separated:

```
live_keys=1 tombstones=0 total_records=1 dead_records=0 segment_count=1 bytes_on_disk=18
```

Other rules:

1. A usage problem exits **2**: unknown command, missing or extra arguments, a
   `max_segment_bytes` that is not a positive integer. The message goes to **stderr**.
   Let `argparse` produce these where you can.
2. `--max-segment-bytes N` is an optional global flag, default `4096`.
3. A `ValueError` or `TypeError` from the store (for instance an over-long key) is reported
   on stderr and exits **2**.
4. A `CorruptSegmentError` is reported on stderr and exits **3**.
5. Nothing is ever printed to stdout on a failure path.
6. There must be a `main(argv: list[str] | None = None) -> int` function returning the exit
   code, and `python -m kvstore` must pass its return value to `sys.exit`.

## 8. Errors

`errors.py` defines exactly:

```
KVStoreError(Exception)
├── RecordError(KVStoreError)
│   ├── IncompleteRecordError(RecordError)
│   └── CorruptRecordError(RecordError)
└── CorruptSegmentError(KVStoreError)
```

`CorruptSegmentError.__init__(self, path, offset, reason)` stores `path`, `offset` and
`reason`, and its `str()` contains the file name and the decimal offset.

## 9. `kvstore/__init__.py`

Re-export exactly these names in `__all__`:

```
KVStore, Stats, Index, Location, Segment, CompactionResult, compact,
encode_record, decode_record,
KVStoreError, RecordError, IncompleteRecordError, CorruptRecordError, CorruptSegmentError
```

## 10. Your own tests

`tests/test_kvstore.py`, at least **30** test functions, runnable with `python -m pytest -q`
from this folder. Cover at minimum: the record codec round trip, a tombstone versus an
empty value, truncated tail recovery, a CRC mismatch being reported as corruption,
rollover, `keys()` ordering, compaction, and the CLI exit codes. Use `tmp_path`.

## Acceptance criteria

1. `python -m pytest -q` passes from this folder.
2. `python -c "import kvstore; print(sorted(kvstore.__all__))"` works.
3. Round trip:
   ```
   python -m kvstore ./data set a 1     # exit 0
   python -m kvstore ./data get a       # prints 1, exit 0
   python -m kvstore ./data get zz      # prints nothing, exit 1
   python -m kvstore ./data list        # prints a
   python -m kvstore ./data stats       # one line, six fields
   ```
4. Every public function and method has type annotations on parameters and return value.
5. No function body is longer than 60 lines.
