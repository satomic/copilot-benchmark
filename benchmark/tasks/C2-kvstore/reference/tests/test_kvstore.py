"""Reference test suite for kvstore."""

from __future__ import annotations

import struct
import subprocess
import sys
import zlib

import pytest

from kvstore import (
    CorruptSegmentError,
    KVStore,
    Location,
    compact,
    decode_record,
    encode_record,
)
from kvstore.errors import CorruptRecordError, IncompleteRecordError
from kvstore.index import Index
from kvstore.record import HEADER_SIZE


def test_encode_decode_round_trip():
    blob = encode_record("k", "v")
    assert decode_record(blob) == ("k", "v", len(blob))


def test_encode_tombstone_is_header_only():
    assert len(encode_record("k", None)) == HEADER_SIZE + 1


def test_tombstone_decodes_to_none():
    key, value, size = decode_record(encode_record("k", None))
    assert (key, value) == ("k", None)
    assert size == HEADER_SIZE + 1


def test_empty_value_is_not_a_tombstone():
    key, value, _ = decode_record(encode_record("k", ""))
    assert value == ""


def test_crc_covers_body_only():
    blob = bytearray(encode_record("k", "v"))
    body = bytes(blob[HEADER_SIZE:])
    assert struct.unpack_from(">I", blob, 11)[0] == zlib.crc32(body)


def test_decode_rejects_bad_magic():
    blob = bytearray(encode_record("k", "v"))
    blob[0:4] = b"XXXX"
    with pytest.raises(CorruptRecordError):
        decode_record(bytes(blob))


def test_decode_rejects_crc_mismatch():
    blob = bytearray(encode_record("k", "v"))
    blob[-1] ^= 0xFF
    with pytest.raises(CorruptRecordError):
        decode_record(bytes(blob))


def test_decode_incomplete_header():
    with pytest.raises(IncompleteRecordError):
        decode_record(encode_record("k", "v")[:5])


def test_decode_incomplete_body():
    with pytest.raises(IncompleteRecordError):
        decode_record(encode_record("k", "value")[:-2])


def test_encode_rejects_empty_key():
    with pytest.raises(ValueError):
        encode_record("", "v")


def test_set_then_get(tmp_path):
    with KVStore(tmp_path) as store:
        store.set("a", "1")
        assert store.get("a") == "1"


def test_get_missing_is_none(tmp_path):
    with KVStore(tmp_path) as store:
        assert store.get("nope") is None


def test_empty_value_round_trips(tmp_path):
    with KVStore(tmp_path) as store:
        store.set("a", "")
        assert store.get("a") == ""


def test_delete_live_key(tmp_path):
    with KVStore(tmp_path) as store:
        store.set("a", "1")
        assert store.delete("a") is True
        assert store.get("a") is None


def test_delete_absent_key_writes_nothing(tmp_path):
    with KVStore(tmp_path) as store:
        before = store.stats().total_records
        assert store.delete("ghost") is False
        assert store.stats().total_records == before


def test_double_delete_returns_false(tmp_path):
    with KVStore(tmp_path) as store:
        store.set("a", "1")
        store.delete("a")
        assert store.delete("a") is False


def test_reopen_sees_data(tmp_path):
    with KVStore(tmp_path) as store:
        store.set("a", "1")
    with KVStore(tmp_path) as store:
        assert store.get("a") == "1"


def test_reopen_respects_tombstone(tmp_path):
    with KVStore(tmp_path) as store:
        store.set("a", "1")
        store.delete("a")
    with KVStore(tmp_path) as store:
        assert store.get("a") is None
        assert store.keys() == []


def test_keys_order_follows_newest_record(tmp_path):
    with KVStore(tmp_path) as store:
        store.set("a", "1")
        store.set("b", "2")
        store.set("a", "3")
        assert store.keys() == ["b", "a"]


def test_rollover_creates_new_segment(tmp_path):
    with KVStore(tmp_path, max_segment_bytes=40) as store:
        store.set("a", "x" * 10)
        store.set("b", "y" * 10)
        assert store.stats().segment_count == 2


def test_oversized_record_fits_empty_segment(tmp_path):
    with KVStore(tmp_path, max_segment_bytes=16) as store:
        store.set("a", "z" * 100)
        assert store.get("a") == "z" * 100


def test_key_type_must_be_str(tmp_path):
    with KVStore(tmp_path) as store:
        with pytest.raises(TypeError):
            store.set(b"a", "1")


def test_value_type_must_be_str(tmp_path):
    with KVStore(tmp_path) as store:
        with pytest.raises(TypeError):
            store.set("a", 1)


def test_key_byte_limit(tmp_path):
    with KVStore(tmp_path) as store:
        with pytest.raises(ValueError):
            store.set("中" * 30000, "1")


def test_min_segment_bytes(tmp_path):
    with pytest.raises(ValueError):
        KVStore(tmp_path, max_segment_bytes=4)


def test_closed_store_raises(tmp_path):
    store = KVStore(tmp_path)
    store.close()
    with pytest.raises(ValueError):
        store.get("a")


def test_close_is_idempotent(tmp_path):
    store = KVStore(tmp_path)
    store.close()
    store.close()


def test_truncated_tail_is_ignored(tmp_path):
    with KVStore(tmp_path) as store:
        store.set("a", "1")
    seg = tmp_path / "000001.seg"
    seg.write_bytes(seg.read_bytes() + encode_record("b", "2")[:-3])
    with KVStore(tmp_path) as store:
        assert store.keys() == ["a"]


def test_mid_file_corruption_raises(tmp_path):
    with KVStore(tmp_path) as store:
        store.set("a", "1")
        store.set("b", "2")
    seg = tmp_path / "000001.seg"
    data = bytearray(seg.read_bytes())
    data[-1] ^= 0xFF
    seg.write_bytes(bytes(data))
    with pytest.raises(CorruptSegmentError):
        KVStore(tmp_path)


def test_corrupt_error_reports_offset(tmp_path):
    with KVStore(tmp_path) as store:
        store.set("a", "1")
    seg = tmp_path / "000001.seg"
    data = bytearray(seg.read_bytes())
    data[-1] ^= 0xFF
    seg.write_bytes(bytes(data))
    with pytest.raises(CorruptSegmentError) as info:
        KVStore(tmp_path)
    assert info.value.offset == 0
    assert "000001.seg" in str(info.value)


def test_non_segment_files_ignored(tmp_path):
    (tmp_path / "000002.seg.tmp").write_bytes(b"garbage")
    (tmp_path / "notes.txt").write_text("hi")
    with KVStore(tmp_path) as store:
        store.set("a", "1")
        assert store.stats().segment_count == 1


def test_stats_fields(tmp_path):
    with KVStore(tmp_path) as store:
        store.set("a", "1")
        store.set("a", "2")
        store.set("b", "3")
        store.delete("b")
        stats = store.stats()
        assert (stats.live_keys, stats.tombstones) == (1, 1)
        assert stats.total_records == 4
        assert stats.dead_records == 2


def test_compact_drops_tombstones(tmp_path):
    with KVStore(tmp_path) as store:
        store.set("a", "1")
        store.set("b", "2")
        store.delete("b")
        result = compact(store)
        assert result.records_written == 1
        assert store.keys() == ["a"]
        assert store.stats().tombstones == 0


def test_compact_preserves_key_order(tmp_path):
    with KVStore(tmp_path, max_segment_bytes=32) as store:
        for key in ("a", "b", "c"):
            store.set(key, key)
        store.set("a", "again")
        expected = store.keys()
        compact(store)
        assert store.keys() == expected


def test_compact_leaves_one_segment(tmp_path):
    with KVStore(tmp_path, max_segment_bytes=20) as store:
        for i in range(5):
            store.set(f"k{i}", "v")
        compact(store)
        assert store.stats().segment_count == 1


def test_compact_removes_tmp_file(tmp_path):
    with KVStore(tmp_path) as store:
        store.set("a", "1")
        compact(store)
    assert not list(tmp_path.glob("*.tmp"))


def test_writes_after_compaction(tmp_path):
    with KVStore(tmp_path) as store:
        store.set("a", "1")
        compact(store)
        store.set("b", "2")
        assert store.get("b") == "2"
        assert store.keys() == ["a", "b"]


def test_index_put_and_get():
    index = Index()
    index.put("a", Location(1, 0), tombstone=False)
    assert index.get("a") == Location(1, 0)
    index.put("a", Location(1, 10), tombstone=True)
    assert index.get("a") is None


def test_index_live_keys_sorted_by_location():
    index = Index()
    index.put("late", Location(2, 0), tombstone=False)
    index.put("early", Location(1, 5), tombstone=False)
    assert index.live_keys() == ["early", "late"]


def _cli(root, *args):
    return subprocess.run(
        [sys.executable, "-m", "kvstore", str(root), *args],
        capture_output=True,
        text=True,
    )


def test_cli_set_get(tmp_path):
    assert _cli(tmp_path, "set", "a", "1").returncode == 0
    done = _cli(tmp_path, "get", "a")
    assert done.returncode == 0
    assert done.stdout == "1\n"


def test_cli_get_missing_exit_1(tmp_path):
    done = _cli(tmp_path, "get", "ghost")
    assert done.returncode == 1
    assert done.stdout == ""


def test_cli_usage_error_exit_2(tmp_path):
    assert _cli(tmp_path, "frobnicate").returncode == 2


def test_cli_list_and_stats(tmp_path):
    _cli(tmp_path, "set", "a", "1")
    assert _cli(tmp_path, "list").stdout == "a\n"
    assert _cli(tmp_path, "stats").stdout.startswith("live_keys=1 tombstones=0")
