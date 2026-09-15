"""Tests for the append-only key-value store."""

from __future__ import annotations

import struct
import zlib
from pathlib import Path

import pytest

from kvstore import (
    CompactionResult,
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
from kvstore.__main__ import main
from kvstore.record import FLAG_TOMBSTONE, FLAG_VALUE, HEADER_SIZE, MAGIC


def test_encode_decode_roundtrip() -> None:
    blob = encode_record("alpha", "beta")
    key, value, size = decode_record(blob)
    assert (key, value, size) == ("alpha", "beta", len(blob))


def test_tombstone_versus_empty_value() -> None:
    empty = encode_record("k", "")
    tomb = encode_record("k", None)
    assert empty != tomb
    assert decode_record(empty)[1] == ""
    assert decode_record(tomb)[1] is None
    assert len(empty) == len(tomb) == HEADER_SIZE + 1


def test_decode_incomplete_header() -> None:
    blob = encode_record("k", "v")
    with pytest.raises(IncompleteRecordError):
        decode_record(blob[:10])


def test_decode_incomplete_payload() -> None:
    blob = encode_record("hello", "world")
    with pytest.raises(IncompleteRecordError):
        decode_record(blob[: HEADER_SIZE + 2])


def test_decode_bad_magic() -> None:
    blob = bytearray(encode_record("k", "v"))
    blob[0:4] = b"XXXX"
    with pytest.raises(CorruptRecordError, match="bad magic"):
        decode_record(bytes(blob))


def test_decode_unknown_flags() -> None:
    blob = bytearray(encode_record("k", "v"))
    blob[4] = 0x02
    with pytest.raises(CorruptRecordError, match="unknown flags"):
        decode_record(bytes(blob))


def test_decode_zero_key_len() -> None:
    crc = zlib.crc32(b"") & 0xFFFFFFFF
    header = struct.pack(">4sBHII", MAGIC, FLAG_VALUE, 0, 0, crc)
    with pytest.raises(CorruptRecordError, match="empty key"):
        decode_record(header)


def test_decode_tombstone_with_value() -> None:
    payload = b"k" + b"v"
    crc = zlib.crc32(payload) & 0xFFFFFFFF
    blob = struct.pack(">4sBHII", MAGIC, FLAG_TOMBSTONE, 1, 1, crc) + payload
    with pytest.raises(CorruptRecordError, match="tombstone with value"):
        decode_record(blob)


def test_decode_crc_mismatch() -> None:
    blob = bytearray(encode_record("k", "v"))
    blob[-1] ^= 0xFF
    with pytest.raises(CorruptRecordError, match="crc mismatch"):
        decode_record(bytes(blob))


def test_decode_invalid_utf8() -> None:
    key_bytes = b"\xff"
    crc = zlib.crc32(key_bytes) & 0xFFFFFFFF
    blob = struct.pack(">4sBHII", MAGIC, FLAG_VALUE, 1, 0, crc) + key_bytes
    with pytest.raises(CorruptRecordError, match="invalid utf-8"):
        decode_record(blob)


def test_crc_checked_before_utf8() -> None:
    key_bytes = b"\xff"
    blob = struct.pack(">4sBHII", MAGIC, FLAG_VALUE, 1, 0, 0) + key_bytes
    with pytest.raises(CorruptRecordError, match="crc mismatch"):
        decode_record(blob)


def test_decode_offset_roundtrip() -> None:
    first = encode_record("a", "1")
    second = encode_record("b", "2")
    buf = first + second
    key, value, size = decode_record(buf, len(first))
    assert (key, value, size) == ("b", "2", len(second))


def test_truncated_tail_recovery(tmp_path: Path) -> None:
    store = KVStore(tmp_path)
    store.set("keep", "yes")
    store.close()
    seg = next(tmp_path.glob("*.seg"))
    with open(seg, "ab") as fh:
        fh.write(b"\x00\x01\x02\x03\x04")
    with KVStore(tmp_path) as reopened:
        assert reopened.get("keep") == "yes"
        assert reopened.stats().bytes_on_disk > 15


def test_crc_mismatch_is_corruption_even_at_end(tmp_path: Path) -> None:
    store = KVStore(tmp_path)
    store.set("k", "v")
    store.close()
    seg = next(tmp_path.glob("*.seg"))
    data = bytearray(seg.read_bytes())
    data[-1] ^= 0x01
    seg.write_bytes(data)
    with pytest.raises(CorruptSegmentError):
        KVStore(tmp_path)


def test_corrupt_segment_str_contains_name_and_offset(tmp_path: Path) -> None:
    path = tmp_path / "000001.seg"
    blob = bytearray(encode_record("k", "v"))
    blob[0:4] = b"NOPE"
    path.write_bytes(bytes(blob))
    with pytest.raises(CorruptSegmentError) as info:
        KVStore(tmp_path)
    text = str(info.value)
    assert "000001.seg" in text
    assert "0" in text
    assert info.value.offset == 0
    assert info.value.path.name == "000001.seg"


def test_set_get_persist_reopen(tmp_path: Path) -> None:
    with KVStore(tmp_path) as store:
        store.set("city", "paris")
    with KVStore(tmp_path) as store:
        assert store.get("city") == "paris"


def test_delete_live_and_noop(tmp_path: Path) -> None:
    with KVStore(tmp_path) as store:
        store.set("x", "1")
        assert store.delete("x") is True
        assert store.get("x") is None
        assert store.delete("x") is False
        assert store.delete("missing") is False
        assert store.stats().total_records == 2


def test_empty_value_is_not_none(tmp_path: Path) -> None:
    with KVStore(tmp_path) as store:
        store.set("blank", "")
        assert store.get("blank") == ""
        assert store.keys() == ["blank"]


def test_keys_ordering(tmp_path: Path) -> None:
    with KVStore(tmp_path) as store:
        store.set("b", "1")
        store.set("a", "2")
        store.set("c", "3")
        assert store.keys() == ["b", "a", "c"]


def test_rewrite_moves_key_to_end(tmp_path: Path) -> None:
    with KVStore(tmp_path) as store:
        store.set("a", "1")
        store.set("b", "2")
        store.set("a", "3")
        assert store.keys() == ["b", "a"]
        assert store.get("a") == "3"


def test_rollover(tmp_path: Path) -> None:
    with KVStore(tmp_path, max_segment_bytes=40) as store:
        store.set("one", "1111")
        store.set("two", "2222")
        store.set("three", "3333")
        assert store.stats().segment_count >= 2
        assert store.get("one") == "1111"
        assert store.get("three") == "3333"


def test_empty_segment_accepts_large_record(tmp_path: Path) -> None:
    payload = "z" * 200
    with KVStore(tmp_path, max_segment_bytes=16) as store:
        store.set("k", payload)
        assert store.get("k") == payload
        assert store.stats().segment_count == 1


def test_exact_max_segment_fits(tmp_path: Path) -> None:
    first = encode_record("a", "b")
    with KVStore(tmp_path, max_segment_bytes=len(first)) as store:
        store.set("a", "b")
        store.set("c", "d")
        assert store.stats().segment_count == 2


def test_key_type_error(tmp_path: Path) -> None:
    with KVStore(tmp_path) as store:
        with pytest.raises(TypeError):
            store.set(b"k", "v")  # type: ignore[arg-type]


def test_value_type_error(tmp_path: Path) -> None:
    with KVStore(tmp_path) as store:
        with pytest.raises(TypeError):
            store.set("k", b"v")  # type: ignore[arg-type]


def test_key_too_long(tmp_path: Path) -> None:
    with KVStore(tmp_path) as store:
        with pytest.raises(ValueError):
            store.set("你" * 40000, "v")


def test_empty_key_rejected(tmp_path: Path) -> None:
    with KVStore(tmp_path) as store:
        with pytest.raises(ValueError):
            store.set("", "v")


def test_max_segment_bytes_validation(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        KVStore(tmp_path, max_segment_bytes=15)
    with pytest.raises(ValueError):
        KVStore(tmp_path, max_segment_bytes=16.0)  # type: ignore[arg-type]


def test_closed_store_raises(tmp_path: Path) -> None:
    store = KVStore(tmp_path)
    store.close()
    with pytest.raises(ValueError):
        store.get("k")


def test_close_idempotent(tmp_path: Path) -> None:
    store = KVStore(tmp_path)
    store.close()
    store.close()


def test_context_manager(tmp_path: Path) -> None:
    with KVStore(tmp_path) as store:
        store.set("a", "1")
    with pytest.raises(ValueError):
        store.keys()


def test_compaction_drops_tombstones(tmp_path: Path) -> None:
    with KVStore(tmp_path) as store:
        store.set("keep", "1")
        store.set("gone", "2")
        store.delete("gone")
        store.set("keep", "3")
        before = store.stats()
        result = compact(store)
        assert store.get("keep") == "3"
        assert store.get("gone") is None
        assert "gone" not in store.keys()
        assert store.stats().tombstones == 0
        assert result.records_written == 1
        assert result.records_dropped == before.total_records - 1
        assert result.segments_removed >= 1


def test_compaction_preserves_key_order(tmp_path: Path) -> None:
    with KVStore(tmp_path) as store:
        store.set("b", "1")
        store.set("a", "2")
        store.set("c", "3")
        store.set("a", "4")
        order = store.keys()
        compact(store)
        assert store.keys() == order == ["b", "c", "a"]


def test_compaction_empty_store(tmp_path: Path) -> None:
    with KVStore(tmp_path) as store:
        result = compact(store)
        assert result.records_written == 0
        assert store.stats().segment_count == 1
        store.set("after", "yes")
        assert store.get("after") == "yes"


def test_compaction_result_type(tmp_path: Path) -> None:
    with KVStore(tmp_path) as store:
        store.set("k", "v")
        result = compact(store)
        assert isinstance(result, CompactionResult)


def test_cli_set_get(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main([str(tmp_path), "set", "a", "1"]) == 0
    capsys.readouterr()
    assert main([str(tmp_path), "get", "a"]) == 0
    out, err = capsys.readouterr()
    assert out == "1\n"
    assert err == ""


def test_cli_get_missing(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code = main([str(tmp_path), "get", "zz"])
    out, err = capsys.readouterr()
    assert code == 1
    assert out == ""
    assert err == ""


def test_cli_delete_codes(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    main([str(tmp_path), "set", "a", "1"])
    capsys.readouterr()
    assert main([str(tmp_path), "delete", "a"]) == 0
    assert main([str(tmp_path), "delete", "a"]) == 1
    out, err = capsys.readouterr()
    assert out == ""


def test_cli_stats_and_list(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    main([str(tmp_path), "set", "a", "1"])
    capsys.readouterr()
    assert main([str(tmp_path), "list"]) == 0
    out, _ = capsys.readouterr()
    assert out == "a\n"
    assert main([str(tmp_path), "stats"]) == 0
    out, _ = capsys.readouterr()
    parts = out.strip().split()
    assert len(parts) == 6
    assert parts[0].startswith("live_keys=")
    assert parts[5].startswith("bytes_on_disk=")


def test_cli_compact(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    main([str(tmp_path), "set", "a", "1"])
    capsys.readouterr()
    assert main([str(tmp_path), "compact"]) == 0
    out, _ = capsys.readouterr()
    assert out.startswith("removed=")
    assert "written=" in out
    assert "dropped=" in out
    assert "reclaimed=" in out


def test_cli_usage_exit_2(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main([str(tmp_path), "nope"]) == 2
    out, err = capsys.readouterr()
    assert out == ""
    assert err != ""


def test_cli_value_error_exit_2(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main([str(tmp_path), "set", "", "v"]) == 2
    out, err = capsys.readouterr()
    assert out == ""
    assert err != ""


def test_cli_corrupt_exit_3(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    main([str(tmp_path), "set", "a", "1"])
    capsys.readouterr()
    seg = next(tmp_path.glob("*.seg"))
    data = bytearray(seg.read_bytes())
    data[-1] ^= 0x01
    seg.write_bytes(data)
    code = main([str(tmp_path), "get", "a"])
    out, err = capsys.readouterr()
    assert code == 3
    assert out == ""
    assert err != ""


def test_stats_dead_records(tmp_path: Path) -> None:
    with KVStore(tmp_path) as store:
        store.set("a", "1")
        store.set("a", "2")
        store.set("b", "3")
        store.delete("b")
        s = store.stats()
        assert s.live_keys == 1
        assert s.tombstones == 1
        assert s.total_records == 4
        assert s.dead_records == 2


def test_ignore_non_segment_files(tmp_path: Path) -> None:
    with KVStore(tmp_path) as store:
        store.set("a", "1")
    (tmp_path / "000003.seg.tmp").write_bytes(encode_record("ghost", "nope"))
    (tmp_path / "notes.txt").write_text("ignore")
    with KVStore(tmp_path) as store:
        assert store.get("ghost") is None
        assert store.get("a") == "1"


def test_index_tombstone_count() -> None:
    idx = Index()
    idx.put("a", Location(1, 0), tombstone=False)
    idx.put("b", Location(1, 10), tombstone=True)
    idx.put("a", Location(1, 20), tombstone=True)
    assert len(idx) == 0
    assert idx.tombstone_count() == 2
    assert idx.get("a") is None
    assert idx.live_keys() == []


def test_delete_writes_nothing_on_noop(tmp_path: Path) -> None:
    with KVStore(tmp_path) as store:
        store.set("a", "1")
        size = store.stats().bytes_on_disk
        store.delete("missing")
        assert store.stats().bytes_on_disk == size


def test_segment_scan_and_append(tmp_path: Path) -> None:
    path = tmp_path / "000001.seg"
    seg = Segment(path, 1)
    off = seg.append(encode_record("k", "v"))
    assert off == 0
    rows = list(seg.scan())
    assert rows == [("k", "v", 0)]
    seg.close()


def test_unicode_key_and_value(tmp_path: Path) -> None:
    with KVStore(tmp_path) as store:
        store.set("键", "值")
        assert store.get("键") == "值"


def test_later_records_win_across_segments(tmp_path: Path) -> None:
    with KVStore(tmp_path, max_segment_bytes=30) as store:
        store.set("k", "old")
        store.set("k", "new")
        assert store.get("k") == "new"
    with KVStore(tmp_path, max_segment_bytes=30) as store:
        assert store.get("k") == "new"


def test_cli_max_segment_bytes_not_int(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code = main([str(tmp_path), "--max-segment-bytes", "nope", "list"])
    out, err = capsys.readouterr()
    assert code == 2
    assert out == ""
    assert err != ""
