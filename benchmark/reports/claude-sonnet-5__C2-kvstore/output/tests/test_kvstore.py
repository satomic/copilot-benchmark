"""Test suite for the kvstore package."""

from __future__ import annotations

import pathlib
import subprocess
import sys

import pytest

import kvstore
from kvstore import (
    CorruptRecordError,
    CorruptSegmentError,
    IncompleteRecordError,
    Index,
    KVStore,
    Location,
    Segment,
    compact,
    decode_record,
    encode_record,
)


# ---------- record codec ----------


def test_record_roundtrip_value() -> None:
    blob = encode_record("hello", "world")
    key, value, size = decode_record(blob)
    assert key == "hello"
    assert value == "world"
    assert size == len(blob)


def test_record_roundtrip_tombstone() -> None:
    blob = encode_record("hello", None)
    key, value, size = decode_record(blob)
    assert key == "hello"
    assert value is None
    assert size == 15 + 5


def test_record_empty_value_not_tombstone() -> None:
    blob_empty = encode_record("k", "")
    blob_tomb = encode_record("k", None)
    assert len(blob_empty) == len(blob_tomb) == 16
    _, v1, _ = decode_record(blob_empty)
    _, v2, _ = decode_record(blob_tomb)
    assert v1 == ""
    assert v2 is None


def test_record_decode_with_offset() -> None:
    blob1 = encode_record("a", "1")
    blob2 = encode_record("bb", "22")
    buf = blob1 + blob2
    key, value, size = decode_record(buf, len(blob1))
    assert key == "bb"
    assert value == "22"
    assert size == len(blob2)


def test_record_incomplete_header() -> None:
    with pytest.raises(IncompleteRecordError):
        decode_record(b"KVR1\x00")


def test_record_incomplete_body() -> None:
    blob = encode_record("hello", "world")
    with pytest.raises(IncompleteRecordError):
        decode_record(blob[:-3])


def test_record_bad_magic() -> None:
    blob = bytearray(encode_record("a", "b"))
    blob[0:4] = b"XXXX"
    with pytest.raises(CorruptRecordError):
        decode_record(bytes(blob))


def test_record_bad_flags() -> None:
    blob = bytearray(encode_record("a", "b"))
    blob[4] = 0x02
    with pytest.raises(CorruptRecordError):
        decode_record(bytes(blob))


def test_record_key_len_zero() -> None:
    blob = bytearray(encode_record("a", "b"))
    blob[5:7] = (0).to_bytes(2, "big")
    with pytest.raises(CorruptRecordError):
        decode_record(bytes(blob))


def test_record_tombstone_nonzero_value_len() -> None:
    blob = bytearray(encode_record("a", None))
    blob[7:11] = (5).to_bytes(4, "big")
    with pytest.raises(CorruptRecordError):
        decode_record(bytes(blob))


def test_record_crc_mismatch() -> None:
    blob = bytearray(encode_record("hello", "world"))
    blob[-1] ^= 0xFF
    with pytest.raises(CorruptRecordError):
        decode_record(bytes(blob))


def test_record_invalid_utf8_key() -> None:
    # Craft a record with invalid utf-8 bytes in the key but correct crc.
    import zlib

    key_bytes = b"\xff\xfe"
    value_bytes = b""
    crc = zlib.crc32(key_bytes + value_bytes) & 0xFFFFFFFF
    import struct

    header = struct.pack(">4sBHIL", b"KVR1", 0x00, len(key_bytes), len(value_bytes), crc)
    with pytest.raises(CorruptRecordError):
        decode_record(header + key_bytes + value_bytes)


def test_record_structural_checked_before_crc() -> None:
    # key_len == 0 must raise CorruptRecordError even if crc "matches" garbage.
    import struct

    header = struct.pack(">4sBHIL", b"KVR1", 0x00, 0, 0, 0)
    with pytest.raises(CorruptRecordError):
        decode_record(header)


def test_record_key_too_long_rejected() -> None:
    with pytest.raises(ValueError):
        encode_record("x" * 70000, "v")


# ---------- Segment ----------


def test_segment_append_and_scan(tmp_path: pathlib.Path) -> None:
    path = tmp_path / "000001.seg"
    seg = Segment(path, 1)
    off1 = seg.append(encode_record("a", "1"))
    off2 = seg.append(encode_record("b", "2"))
    assert off1 == 0
    results = list(seg.scan())
    seg.close()
    assert results == [("a", "1", off1), ("b", "2", off2)]


def test_segment_truncated_tail(tmp_path: pathlib.Path) -> None:
    path = tmp_path / "000001.seg"
    seg = Segment(path, 1)
    seg.append(encode_record("a", "1"))
    seg.close()
    with open(path, "ab") as fh:
        fh.write(b"KVR1\x00\x00\x05")  # partial header
    seg2 = Segment(path, 1)
    results = list(seg2.scan())
    seg2.close()
    assert results == [("a", "1", 0)]


def test_segment_corrupt_record_raises(tmp_path: pathlib.Path) -> None:
    path = tmp_path / "000001.seg"
    seg = Segment(path, 1)
    blob = bytearray(encode_record("a", "1"))
    blob[-1] ^= 0xFF
    seg.append(bytes(blob))
    seg.close()
    seg2 = Segment(path, 1)
    with pytest.raises(CorruptSegmentError) as exc_info:
        list(seg2.scan())
    seg2.close()
    err = exc_info.value
    assert err.path == path
    assert err.offset == 0
    assert "000001.seg" in str(err)
    assert "0" in str(err)


def test_segment_corrupt_as_last_record(tmp_path: pathlib.Path) -> None:
    path = tmp_path / "000001.seg"
    seg = Segment(path, 1)
    seg.append(encode_record("a", "1"))
    bad = bytearray(encode_record("b", "2"))
    bad[-1] ^= 0xFF
    seg.append(bytes(bad))
    seg.close()
    seg2 = Segment(path, 1)
    gen = seg2.scan()
    first = next(gen)
    assert first[0] == "a"
    with pytest.raises(CorruptSegmentError):
        next(gen)
    seg2.close()


def test_segment_size(tmp_path: pathlib.Path) -> None:
    path = tmp_path / "000001.seg"
    seg = Segment(path, 1)
    assert seg.size == 0
    seg.append(encode_record("a", "1"))
    assert seg.size == len(encode_record("a", "1"))
    seg.close()


# ---------- Index ----------


def test_index_basic_put_get() -> None:
    idx = Index()
    idx.put("a", Location(1, 0), tombstone=False)
    assert idx.get("a") == Location(1, 0)
    assert len(idx) == 1


def test_index_tombstone_hides_key() -> None:
    idx = Index()
    idx.put("a", Location(1, 0), tombstone=False)
    idx.put("a", Location(1, 20), tombstone=True)
    assert idx.get("a") is None
    assert len(idx) == 0
    assert idx.tombstone_count() == 1


def test_index_live_keys_ordering() -> None:
    idx = Index()
    idx.put("a", Location(1, 0), tombstone=False)
    idx.put("b", Location(1, 10), tombstone=False)
    idx.put("a", Location(1, 20), tombstone=False)  # rewrite moves 'a' to end
    assert idx.live_keys() == ["b", "a"]


def test_index_absent_key() -> None:
    idx = Index()
    assert idx.get("missing") is None


# ---------- KVStore basics ----------


def test_store_set_get(tmp_path: pathlib.Path) -> None:
    store = KVStore(tmp_path)
    store.set("k", "v")
    assert store.get("k") == "v"
    store.close()


def test_store_empty_value_is_not_none(tmp_path: pathlib.Path) -> None:
    store = KVStore(tmp_path)
    store.set("k", "")
    assert store.get("k") == ""
    store.close()


def test_store_get_missing_returns_none(tmp_path: pathlib.Path) -> None:
    store = KVStore(tmp_path)
    assert store.get("nope") is None
    store.close()


def test_store_delete_live_key(tmp_path: pathlib.Path) -> None:
    store = KVStore(tmp_path)
    store.set("k", "v")
    assert store.delete("k") is True
    assert store.get("k") is None
    store.close()


def test_store_delete_noop_does_not_grow_log(tmp_path: pathlib.Path) -> None:
    store = KVStore(tmp_path)
    assert store.delete("missing") is False
    size_before = store.stats().bytes_on_disk
    assert store.delete("missing") is False
    size_after = store.stats().bytes_on_disk
    assert size_before == size_after == 0
    store.close()


def test_store_delete_already_tombstoned(tmp_path: pathlib.Path) -> None:
    store = KVStore(tmp_path)
    store.set("k", "v")
    store.delete("k")
    assert store.delete("k") is False
    store.close()


def test_store_reopen_recovers_state(tmp_path: pathlib.Path) -> None:
    store = KVStore(tmp_path)
    store.set("a", "1")
    store.set("b", "2")
    store.delete("a")
    store.close()

    store2 = KVStore(tmp_path)
    assert store2.get("a") is None
    assert store2.get("b") == "2"
    assert store2.keys() == ["b"]
    store2.close()


def test_store_keys_order(tmp_path: pathlib.Path) -> None:
    store = KVStore(tmp_path)
    store.set("a", "1")
    store.set("b", "2")
    store.set("a", "3")  # rewrite moves 'a' to the end
    assert store.keys() == ["b", "a"]
    store.close()


def test_store_type_errors(tmp_path: pathlib.Path) -> None:
    store = KVStore(tmp_path)
    with pytest.raises(TypeError):
        store.set(b"bytes-key", "v")
    with pytest.raises(TypeError):
        store.set("k", 123)
    store.close()


def test_store_key_too_long_value_error(tmp_path: pathlib.Path) -> None:
    store = KVStore(tmp_path)
    big_key = "\u4e2d" * 40000  # 3 bytes/char in utf-8 -> way over 65535
    with pytest.raises(ValueError):
        store.set(big_key, "v")
    store.close()


def test_store_max_segment_bytes_validation(tmp_path: pathlib.Path) -> None:
    with pytest.raises(ValueError):
        KVStore(tmp_path, max_segment_bytes=8)


def test_store_closed_raises(tmp_path: pathlib.Path) -> None:
    store = KVStore(tmp_path)
    store.close()
    store.close()  # idempotent
    with pytest.raises(ValueError):
        store.get("k")


def test_store_context_manager(tmp_path: pathlib.Path) -> None:
    with KVStore(tmp_path) as store:
        store.set("k", "v")
    with pytest.raises(ValueError):
        store.get("k")


# ---------- rollover ----------


def test_store_rollover_creates_new_segment(tmp_path: pathlib.Path) -> None:
    store = KVStore(tmp_path, max_segment_bytes=40)
    store.set("a", "1")  # first record, small
    store.set("bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb", "2")  # forces rollover
    store.close()
    seg_files = sorted(tmp_path.glob("*.seg"))
    assert len(seg_files) >= 2


def test_store_rollover_large_record_on_empty_segment(tmp_path: pathlib.Path) -> None:
    store = KVStore(tmp_path, max_segment_bytes=16)
    store.set("k", "this value is definitely longer than 16 bytes total")
    assert store.get("k") is not None
    store.close()
    seg_files = sorted(tmp_path.glob("*.seg"))
    assert len(seg_files) == 1


def test_store_rollover_exact_fit_does_not_roll(tmp_path: pathlib.Path) -> None:
    blob_size = len(encode_record("k", "v"))
    store = KVStore(tmp_path, max_segment_bytes=blob_size)
    store.set("k", "v")
    seg_files_before = sorted(tmp_path.glob("*.seg"))
    assert len(seg_files_before) == 1
    store.close()


# ---------- stats ----------


def test_stats_counts(tmp_path: pathlib.Path) -> None:
    store = KVStore(tmp_path)
    store.set("a", "1")
    store.set("a", "2")  # dead record created
    store.set("b", "3")
    store.delete("b")  # tombstone
    stats = store.stats()
    assert stats.live_keys == 1
    assert stats.tombstones == 1
    assert stats.total_records == 4
    assert stats.dead_records == 4 - 1 - 1
    assert stats.segment_count == 1
    store.close()


def test_stats_bytes_on_disk_includes_truncated_tail(tmp_path: pathlib.Path) -> None:
    store = KVStore(tmp_path)
    store.set("a", "1")
    store.close()
    seg_path = tmp_path / "000001.seg"
    with open(seg_path, "ab") as fh:
        fh.write(b"KVR1\x00\x00")
    store2 = KVStore(tmp_path)
    stats = store2.stats()
    assert stats.bytes_on_disk == seg_path.stat().st_size
    store2.close()


def test_store_append_after_truncated_tail_recovers(tmp_path: pathlib.Path) -> None:
    store = KVStore(tmp_path)
    store.set("a", "1")
    store.close()
    seg_path = tmp_path / "000001.seg"
    with open(seg_path, "ab") as fh:
        fh.write(b"KVR1\x00\x00\x05\x00\x00")  # partial header, truncated tail
    store2 = KVStore(tmp_path)
    assert store2.stats().bytes_on_disk == seg_path.stat().st_size  # tail still counted
    store2.set("z", "9")
    store2.close()

    store3 = KVStore(tmp_path)
    assert store3.get("a") == "1"
    assert store3.get("z") == "9"
    store3.close()


# ---------- corruption on recovery ----------


def test_store_recovery_raises_on_corrupt_segment(tmp_path: pathlib.Path) -> None:
    store = KVStore(tmp_path)
    store.set("a", "1")
    store.close()
    seg_path = tmp_path / "000001.seg"
    data = bytearray(seg_path.read_bytes())
    data[-1] ^= 0xFF
    seg_path.write_bytes(bytes(data))
    with pytest.raises(CorruptSegmentError):
        KVStore(tmp_path)


def test_store_ignores_unmatched_files(tmp_path: pathlib.Path) -> None:
    (tmp_path / "000003.seg.tmp").write_bytes(b"garbage")
    (tmp_path / "notaseg.txt").write_bytes(b"garbage")
    store = KVStore(tmp_path)
    store.set("a", "1")
    assert store.stats().segment_count == 1
    store.close()


# ---------- compaction ----------


def test_compact_removes_tombstones_and_dead_records(tmp_path: pathlib.Path) -> None:
    store = KVStore(tmp_path)
    store.set("a", "1")
    store.set("a", "2")
    store.set("b", "3")
    store.delete("b")
    store.set("c", "4")
    result = compact(store)
    assert result.records_written == 2  # a, c
    assert result.records_dropped == 5 - 2
    assert store.keys() == ["a", "c"]
    assert store.get("a") == "2"
    assert store.get("b") is None
    store.close()


def test_compact_preserves_keys_order(tmp_path: pathlib.Path) -> None:
    store = KVStore(tmp_path)
    store.set("z", "1")
    store.set("y", "2")
    store.set("z", "3")
    before_order = store.keys()
    compact(store)
    assert store.keys() == before_order
    store.close()


def test_compact_active_segment_usable_after(tmp_path: pathlib.Path) -> None:
    store = KVStore(tmp_path)
    store.set("a", "1")
    compact(store)
    store.set("d", "5")
    assert store.get("d") == "5"
    store.close()


def test_compact_empty_store_creates_empty_segment(tmp_path: pathlib.Path) -> None:
    store = KVStore(tmp_path)
    result = compact(store)
    assert result.records_written == 0
    seg_files = sorted(tmp_path.glob("*.seg"))
    assert len(seg_files) == 1
    store.close()


def test_compact_survives_reopen(tmp_path: pathlib.Path) -> None:
    store = KVStore(tmp_path)
    store.set("a", "1")
    store.set("b", "2")
    store.delete("a")
    compact(store)
    store.close()
    store2 = KVStore(tmp_path)
    assert store2.get("b") == "2"
    assert store2.get("a") is None
    assert store2.stats().segment_count == 1
    store2.close()


def test_compact_bytes_reclaimed_positive(tmp_path: pathlib.Path) -> None:
    store = KVStore(tmp_path)
    store.set("a", "1")
    store.set("a", "2")
    store.set("a", "3")
    result = compact(store)
    assert result.bytes_reclaimed > 0
    store.close()


# ---------- CLI ----------


def _run_cli(root: pathlib.Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "kvstore", str(root), *args],
        cwd=pathlib.Path(__file__).parent.parent,
        capture_output=True,
        text=True,
    )


def test_cli_set_get_roundtrip(tmp_path: pathlib.Path) -> None:
    root = tmp_path / "data"
    r1 = _run_cli(root, "set", "a", "1")
    assert r1.returncode == 0
    assert r1.stdout == ""
    r2 = _run_cli(root, "get", "a")
    assert r2.returncode == 0
    assert r2.stdout == "1\n"


def test_cli_get_missing_exit_1(tmp_path: pathlib.Path) -> None:
    root = tmp_path / "data"
    _run_cli(root, "set", "a", "1")
    r = _run_cli(root, "get", "zz")
    assert r.returncode == 1
    assert r.stdout == ""


def test_cli_delete_noop_exit_1(tmp_path: pathlib.Path) -> None:
    root = tmp_path / "data"
    r = _run_cli(root, "delete", "missing")
    assert r.returncode == 1
    assert r.stdout == ""


def test_cli_list_order(tmp_path: pathlib.Path) -> None:
    root = tmp_path / "data"
    _run_cli(root, "set", "a", "1")
    _run_cli(root, "set", "b", "2")
    r = _run_cli(root, "list")
    assert r.returncode == 0
    assert r.stdout == "a\nb\n"


def test_cli_stats_format(tmp_path: pathlib.Path) -> None:
    root = tmp_path / "data"
    _run_cli(root, "set", "a", "1")
    r = _run_cli(root, "stats")
    assert r.returncode == 0
    assert r.stdout.startswith("live_keys=1 tombstones=0 total_records=1 dead_records=0 segment_count=1 bytes_on_disk=")


def test_cli_compact_output(tmp_path: pathlib.Path) -> None:
    root = tmp_path / "data"
    _run_cli(root, "set", "a", "1")
    _run_cli(root, "delete", "a")
    _run_cli(root, "set", "b", "2")
    r = _run_cli(root, "compact")
    assert r.returncode == 0
    assert r.stdout.startswith("removed=")
    assert "written=1" in r.stdout


def test_cli_unknown_command_exit_2(tmp_path: pathlib.Path) -> None:
    root = tmp_path / "data"
    r = _run_cli(root, "bogus")
    assert r.returncode == 2
    assert r.stdout == ""
    assert r.stderr != ""


def test_cli_missing_args_exit_2(tmp_path: pathlib.Path) -> None:
    root = tmp_path / "data"
    r = _run_cli(root, "set", "onlykey")
    assert r.returncode == 2
    assert r.stdout == ""


def test_cli_value_error_over_long_key_exit_2(tmp_path: pathlib.Path) -> None:
    root = tmp_path / "data"
    big_key = "\u4e2d" * 22000  # 3 bytes/char in utf-8 -> 66000 bytes, short arg string
    r = _run_cli(root, "set", big_key, "v")
    assert r.returncode == 2
    assert r.stdout == ""
    assert r.stderr != ""


def test_cli_corrupt_segment_exit_3(tmp_path: pathlib.Path) -> None:
    root = tmp_path / "data"
    _run_cli(root, "set", "a", "1")
    seg_path = root / "000001.seg"
    data = bytearray(seg_path.read_bytes())
    data[-1] ^= 0xFF
    seg_path.write_bytes(bytes(data))
    r = _run_cli(root, "get", "a")
    assert r.returncode == 3
    assert r.stdout == ""
    assert r.stderr != ""


def test_cli_max_segment_bytes_flag(tmp_path: pathlib.Path) -> None:
    root = tmp_path / "data"
    r = subprocess.run(
        [sys.executable, "-m", "kvstore", str(root), "--max-segment-bytes", "8", "set", "a", "1"],
        cwd=pathlib.Path(__file__).parent.parent,
        capture_output=True,
        text=True,
    )
    assert r.returncode == 2
    assert r.stdout == ""
