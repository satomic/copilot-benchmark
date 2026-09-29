import os
import struct
import subprocess
import sys
import zlib
from pathlib import Path

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
from kvstore.__main__ import main


def test_record_round_trip_ascii() -> None:
    assert decode_record(encode_record("a", "one")) == ("a", "one", 19)


def test_record_round_trip_unicode() -> None:
    blob = encode_record("钥匙", "值")
    assert decode_record(blob) == ("钥匙", "值", len(blob))


def test_tombstone_round_trip() -> None:
    assert decode_record(encode_record("a", None))[1] is None


def test_empty_value_is_not_tombstone() -> None:
    assert decode_record(encode_record("a", ""))[1] == ""


def test_decode_at_offset() -> None:
    blob = b"prefix" + encode_record("a", "b")
    assert decode_record(blob, 6) == ("a", "b", 17)


def test_incomplete_header() -> None:
    with pytest.raises(IncompleteRecordError):
        decode_record(b"KVR1")


def test_incomplete_body() -> None:
    with pytest.raises(IncompleteRecordError):
        decode_record(encode_record("key", "value")[:-1])


def test_bad_magic() -> None:
    blob = bytearray(encode_record("a", "b"))
    blob[0] = 0
    with pytest.raises(CorruptRecordError):
        decode_record(bytes(blob))


def test_unknown_flags() -> None:
    blob = bytearray(encode_record("a", "b"))
    blob[4] = 2
    with pytest.raises(CorruptRecordError):
        decode_record(bytes(blob))


def test_zero_key_length() -> None:
    blob = struct.pack(">4sBHII", b"KVR1", 0, 0, 0, 0)
    with pytest.raises(CorruptRecordError):
        decode_record(blob)


def test_tombstone_with_value_length() -> None:
    blob = struct.pack(">4sBHII", b"KVR1", 1, 1, 1, 0) + b"ab"
    with pytest.raises(CorruptRecordError):
        decode_record(blob)


def test_crc_mismatch() -> None:
    blob = bytearray(encode_record("a", "b"))
    blob[-1] ^= 1
    with pytest.raises(CorruptRecordError, match="CRC"):
        decode_record(bytes(blob))


def test_invalid_utf8_after_valid_crc() -> None:
    payload = b"\xffx"
    blob = struct.pack(">4sBHII", b"KVR1", 0, 1, 1, zlib.crc32(payload)) + payload
    with pytest.raises(CorruptRecordError, match="UTF-8"):
        decode_record(blob)


def test_encode_rejects_empty_key() -> None:
    with pytest.raises(ValueError):
        encode_record("", "x")


def test_encode_rejects_non_string_key() -> None:
    with pytest.raises(TypeError):
        encode_record(b"x", "y")  # type: ignore[arg-type]


def test_encode_rejects_long_utf8_key() -> None:
    with pytest.raises(ValueError):
        encode_record("界" * 40000, "x")


def test_segment_append_offset_and_scan(tmp_path: Path) -> None:
    segment = Segment(tmp_path / "000001.seg", 1)
    assert segment.append(encode_record("a", "1")) == 0
    second = segment.append(encode_record("b", "2"))
    assert list(segment.scan()) == [("a", "1", 0), ("b", "2", second)]
    segment.close()


def test_segment_truncated_tail_is_ignored(tmp_path: Path) -> None:
    path = tmp_path / "000001.seg"
    path.write_bytes(encode_record("a", "1") + encode_record("b", "2")[:8])
    segment = Segment(path, 1)
    assert list(segment.scan()) == [("a", "1", 0)]
    segment.close()


def test_segment_crc_corruption_has_context(tmp_path: Path) -> None:
    path = tmp_path / "000001.seg"
    blob = bytearray(encode_record("a", "1"))
    blob[-1] ^= 1
    path.write_bytes(blob)
    segment = Segment(path, 1)
    with pytest.raises(CorruptSegmentError) as caught:
        list(segment.scan())
    assert caught.value.path == path and caught.value.offset == 0
    assert "000001.seg" in str(caught.value) and "0" in str(caught.value)
    segment.close()


def test_index_live_order() -> None:
    index = Index()
    index.put("b", Location(1, 5), tombstone=False)
    index.put("a", Location(1, 1), tombstone=False)
    assert index.live_keys() == ["a", "b"]


def test_index_rewrite_moves_key() -> None:
    index = Index()
    index.put("a", Location(1, 0), tombstone=False)
    index.put("b", Location(1, 20), tombstone=False)
    index.put("a", Location(2, 0), tombstone=False)
    assert index.live_keys() == ["b", "a"]


def test_index_tombstones() -> None:
    index = Index()
    index.put("a", Location(1, 0), tombstone=True)
    assert index.get("a") is None
    assert index.tombstone_count() == 1
    assert len(index) == 0


def test_store_set_get_reopen(tmp_path: Path) -> None:
    with KVStore(tmp_path) as store:
        store.set("a", "1")
    with KVStore(tmp_path) as store:
        assert store.get("a") == "1"


def test_store_empty_value(tmp_path: Path) -> None:
    with KVStore(tmp_path) as store:
        store.set("a", "")
        assert store.get("a") == ""


def test_store_delete_live(tmp_path: Path) -> None:
    with KVStore(tmp_path) as store:
        store.set("a", "1")
        assert store.delete("a") is True
        assert store.get("a") is None


def test_store_noop_delete_writes_nothing(tmp_path: Path) -> None:
    with KVStore(tmp_path) as store:
        before = store.stats().bytes_on_disk
        assert store.delete("missing") is False
        assert store.stats().bytes_on_disk == before


def test_store_rewrite_key_order(tmp_path: Path) -> None:
    with KVStore(tmp_path) as store:
        store.set("a", "1")
        store.set("b", "2")
        store.set("a", "3")
        assert store.keys() == ["b", "a"]


def test_store_rollover(tmp_path: Path) -> None:
    with KVStore(tmp_path, max_segment_bytes=17) as store:
        store.set("a", "1")
        store.set("b", "2")
        assert store.stats().segment_count == 2


def test_store_exact_limit_does_not_roll(tmp_path: Path) -> None:
    with KVStore(tmp_path, max_segment_bytes=34) as store:
        store.set("a", "1")
        store.set("b", "2")
        assert store.stats().segment_count == 1


def test_oversized_record_fits_empty_segment(tmp_path: Path) -> None:
    with KVStore(tmp_path, max_segment_bytes=16) as store:
        store.set("a", "x" * 100)
        assert store.stats().segment_count == 1


def test_recovery_preserves_truncated_tail_bytes(tmp_path: Path) -> None:
    path = tmp_path / "000001.seg"
    path.write_bytes(encode_record("a", "1") + b"KVR")
    with KVStore(tmp_path) as store:
        assert store.get("a") == "1"
        assert store.stats().bytes_on_disk == path.stat().st_size


def test_write_after_truncated_tail_rolls_over(tmp_path: Path) -> None:
    (tmp_path / "000001.seg").write_bytes(encode_record("a", "1") + b"KVR")
    with KVStore(tmp_path) as store:
        store.set("b", "2")
    with KVStore(tmp_path) as store:
        assert store.get("a") == "1" and store.get("b") == "2"
        assert store.stats().segment_count == 2


def test_non_segment_files_ignored(tmp_path: Path) -> None:
    (tmp_path / "000001.seg.tmp").write_bytes(b"bad")
    (tmp_path / "notes").write_text("bad")
    with KVStore(tmp_path) as store:
        assert store.stats().segment_count == 1


def test_stats_counts_dead_records(tmp_path: Path) -> None:
    with KVStore(tmp_path) as store:
        store.set("a", "1")
        store.set("a", "2")
        store.set("b", "3")
        store.delete("b")
        stats = store.stats()
        assert (
            stats.live_keys,
            stats.tombstones,
            stats.total_records,
            stats.dead_records,
        ) == (1, 1, 4, 2)


def test_closed_store_raises_and_close_is_idempotent(tmp_path: Path) -> None:
    store = KVStore(tmp_path)
    store.close()
    store.close()
    with pytest.raises(ValueError):
        store.keys()


def test_invalid_max_segment_bytes(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        KVStore(tmp_path, max_segment_bytes=15)


def test_set_validates_before_writing(tmp_path: Path) -> None:
    with KVStore(tmp_path) as store:
        with pytest.raises(TypeError):
            store.set("a", None)  # type: ignore[arg-type]
        assert store.stats().bytes_on_disk == 0


def test_compaction_preserves_values_and_order(tmp_path: Path) -> None:
    with KVStore(tmp_path) as store:
        store.set("a", "1")
        store.set("b", "2")
        store.set("a", "3")
        result = compact(store)
        assert store.keys() == ["b", "a"]
        assert store.get("a") == "3"
        assert result.records_written == 2


def test_compaction_drops_tombstones(tmp_path: Path) -> None:
    with KVStore(tmp_path) as store:
        store.set("a", "1")
        store.delete("a")
        result = compact(store)
        assert result.records_written == 0
        assert store.stats().tombstones == 0
        assert store.stats().segment_count == 1


def test_compaction_removes_multiple_segments(tmp_path: Path) -> None:
    with KVStore(tmp_path, max_segment_bytes=17) as store:
        store.set("a", "1")
        store.set("b", "2")
        result = compact(store)
        assert result.segments_removed == 2
        assert store.stats().segment_count == 1


def test_compaction_store_remains_writable(tmp_path: Path) -> None:
    with KVStore(tmp_path) as store:
        store.set("a", "1")
        compact(store)
        store.set("b", "2")
    with KVStore(tmp_path) as store:
        assert store.keys() == ["a", "b"]


def test_public_all_is_exact() -> None:
    assert set(kvstore.__all__) == {
        "KVStore", "Stats", "Index", "Location", "Segment", "CompactionResult",
        "compact", "encode_record", "decode_record", "KVStoreError", "RecordError",
        "IncompleteRecordError", "CorruptRecordError", "CorruptSegmentError",
    }


def test_cli_set_get_and_missing(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main([str(tmp_path), "set", "a", "1"]) == 0
    assert main([str(tmp_path), "get", "a"]) == 0
    assert capsys.readouterr().out == "1\n"
    assert main([str(tmp_path), "get", "missing"]) == 1
    assert capsys.readouterr().out == ""


def test_cli_delete_exit_codes(tmp_path: Path) -> None:
    assert main([str(tmp_path), "delete", "a"]) == 1
    assert main([str(tmp_path), "set", "a", "1"]) == 0
    assert main([str(tmp_path), "delete", "a"]) == 0


def test_cli_list_and_stats(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    main([str(tmp_path), "set", "a", "1"])
    assert main([str(tmp_path), "list"]) == 0
    assert capsys.readouterr().out == "a\n"
    assert main([str(tmp_path), "stats"]) == 0
    assert capsys.readouterr().out.startswith("live_keys=1 tombstones=0 ")


def test_cli_compact_output(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    main([str(tmp_path), "set", "a", "1"])
    assert main([str(tmp_path), "compact"]) == 0
    assert capsys.readouterr().out.startswith("removed=1 written=1 dropped=0 reclaimed=")


def test_cli_usage_exit_code(capsys: pytest.CaptureFixture[str]) -> None:
    assert main([]) == 2
    assert capsys.readouterr().err


def test_cli_invalid_max_exit_code(tmp_path: Path) -> None:
    assert main(["--max-segment-bytes", "0", str(tmp_path), "stats"]) == 2


def test_cli_corruption_exit_code(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (tmp_path / "000001.seg").write_bytes(b"X" * 15)
    assert main([str(tmp_path), "stats"]) == 3
    captured = capsys.readouterr()
    assert captured.out == "" and "000001.seg" in captured.err


def test_module_cli_round_trip(tmp_path: Path) -> None:
    env = os.environ.copy()
    result = subprocess.run(
        [sys.executable, "-m", "kvstore", str(tmp_path), "set", "a", "1"],
        capture_output=True, text=True, env=env, check=False,
    )
    assert result.returncode == 0 and result.stdout == ""
