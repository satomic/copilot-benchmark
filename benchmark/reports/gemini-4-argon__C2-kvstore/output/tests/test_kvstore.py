from __future__ import annotations

import pathlib
import struct
import subprocess
import sys
import zlib
import pytest

import kvstore
from kvstore import (
    CompactionResult,
    CorruptRecordError,
    CorruptSegmentError,
     IncompleteRecordError,
    Index,
    KVStore,
    KVStoreError,
    Location,
    RecordError,
    Segment,
    Stats,
    compact,
    decode_record,
    encode_record,
)
from kvstore.__main__ import main


def test_public_exports() -> None:
    expected = {
        "KVStore",
        "Stats",
        "Index",
        "Location",
        "Segment",
        "CompactionResult",
        "compact",
        "encode_record",
        "decode_record",
        "KVStoreError",
        "RecordError",
        "IncompleteRecordError",
        "CorruptRecordError",
        "CorruptSegmentError",
    }
    assert set(kvstore.__all__) == expected


def test_error_hierarchy() -> None:
    assert issubclass(RecordError, KVStoreError)
    assert issubclass(IncompleteRecordError, RecordError)
    assert issubclass(CorruptRecordError, RecordError)
    assert issubclass(CorruptSegmentError, KVStoreError)
    err = CorruptSegmentError(pathlib.Path("/tmp/000001.seg"), 42, "bad crc")
    assert err.path == pathlib.Path("/tmp/000001.seg")
    assert err.offset == 42
    assert err.reason == "bad crc"
    assert "000001.seg" in str(err)
    assert "42" in str(err)


def test_record_roundtrip_value() -> None:
    blob = encode_record("hello", "world")
    assert len(blob) == 15 + 5 + 5
    assert blob[:4] == b"KVR1"
    assert blob[4] == 0x00
    key, val, size = decode_record(blob)
    assert key == "hello"
    assert val == "world"
    assert size == 25


def test_record_roundtrip_unicode() -> None:
    key_str = "键🔑"
    val_str = "值🌟"
    blob = encode_record(key_str, val_str)
    key, val, size = decode_record(blob)
    assert key == key_str
    assert val == val_str
    assert size == 15 + len(key_str.encode("utf-8")) + len(val_str.encode("utf-8"))


def test_record_tombstone_vs_empty_value() -> None:
    empty_blob = encode_record("k", "")
    tomb_blob = encode_record("k", None)
    assert len(empty_blob) == 16
    assert len(tomb_blob) == 16
    assert empty_blob != tomb_blob
    assert empty_blob[4] == 0x00
    assert tomb_blob[4] == 0x01

    k1, v1, s1 = decode_record(empty_blob)
    k2, v2, s2 = decode_record(tomb_blob)
    assert (k1, v1, s1) == ("k", "", 16)
    assert (k2, v2, s2) == ("k", None, 16)


def test_record_decode_with_offset() -> None:
    b1 = encode_record("a", "1")
    b2 = encode_record("b", "22")
    combined = b"junk" + b1 + b2
    k1, v1, s1 = decode_record(combined, 4)
    assert (k1, v1, s1) == ("a", "1", 17)
    k2, v2, s2 = decode_record(combined, 4 + s1)
    assert (k2, v2, s2) == ("b", "22", 18)


def test_record_crc_covers_only_key_and_value() -> None:
    blob = encode_record("abc", "defg")
    expected_crc = zlib.crc32(b"abcdefg") & 0xFFFFFFFF
    _, _, _, _, crc = struct.unpack(">4sBHII", blob[:15])
    assert crc == expected_crc


def test_record_incomplete_header() -> None:
    blob = encode_record("a", "b")
    for length in range(15):
        with pytest.raises(IncompleteRecordError):
            decode_record(blob[:length])


def test_record_incomplete_payload() -> None:
    blob = encode_record("hello", "world")
    for length in range(15, len(blob)):
        with pytest.raises(IncompleteRecordError):
            decode_record(blob[:length])


def test_record_corrupt_magic() -> None:
    blob = bytearray(encode_record("a", "b"))
    blob[:4] = b"KVR2"
    with pytest.raises(CorruptRecordError):
        decode_record(bytes(blob))


def test_record_corrupt_flags() -> None:
    blob = bytearray(encode_record("a", "b"))
    blob[4] = 0x02
    with pytest.raises(CorruptRecordError):
        decode_record(bytes(blob))


def test_record_corrupt_zero_key_len() -> None:
    crc = zlib.crc32(b"val") & 0xFFFFFFFF
    bad = struct.pack(">4sBHII", b"KVR1", 0x00, 0, 3, crc) + b"val"
    with pytest.raises(CorruptRecordError):
        decode_record(bad)


def test_record_corrupt_tombstone_nonzero_value() -> None:
    crc = zlib.crc32(b"kv") & 0xFFFFFFFF
    bad = struct.pack(">4sBHII", b"KVR1", 0x01, 1, 1, crc) + b"kv"
    with pytest.raises(CorruptRecordError):
        decode_record(bad)


def test_record_corrupt_crc_mismatch() -> None:
    blob = bytearray(encode_record("hello", "world"))
    blob[-1] ^= 0xFF
    with pytest.raises(CorruptRecordError):
        decode_record(bytes(blob))


def test_record_corrupt_utf8_checked_after_crc() -> None:
    bad_key = b"\xff\xfe"
    val = b"ok"
    good_crc = zlib.crc32(bad_key + val) & 0xFFFFFFFF
    rec_good_crc = struct.pack(">4sBHII", b"KVR1", 0x00, 2, 2, good_crc) + bad_key + val
    with pytest.raises(CorruptRecordError, match="UTF-8"):
        decode_record(rec_good_crc)

    bad_crc = (good_crc ^ 1) & 0xFFFFFFFF
    rec_bad_crc = struct.pack(">4sBHII", b"KVR1", 0x00, 2, 2, bad_crc) + bad_key + val
    with pytest.raises(CorruptRecordError, match="CRC"):
        decode_record(rec_bad_crc)


def test_encode_record_validation() -> None:
    with pytest.raises(TypeError):
        encode_record(b"bytes_key", "val")  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        encode_record("k", b"bytes_val")  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        encode_record("", "val")
    with pytest.raises(ValueError):
        encode_record("a" * 65536, "val")
    with pytest.raises(ValueError):
        encode_record("汉" * 40000, "val")


def test_segment_append_and_scan(tmp_path: pathlib.Path) -> None:
    seg_path = tmp_path / "000001.seg"
    seg = Segment(seg_path, 1)
    assert seg.seg_id == 1
    assert seg.size == 0

    b1 = encode_record("k1", "v1")
    b2 = encode_record("k2", None)
    off1 = seg.append(b1)
    off2 = seg.append(b2)
    assert off1 == 0
    assert off2 == len(b1)
    assert seg.size == len(b1) + len(b2)

    records = list(seg.scan())
    assert records == [("k1", "v1", 0), ("k2", None, len(b1))]
    seg.close()


def test_segment_truncated_tail_ignored(tmp_path: pathlib.Path) -> None:
    seg_path = tmp_path / "000001.seg"
    b1 = encode_record("k1", "v1")
    b2 = encode_record("k2", "long_value")
    seg_path.write_bytes(b1 + b2[:18])

    seg = Segment(seg_path, 1)
    records = list(seg.scan())
    assert records == [("k1", "v1", 0)]
    seg.close()


def test_segment_corrupt_last_record_raises(tmp_path: pathlib.Path) -> None:
    seg_path = tmp_path / "000001.seg"
    b1 = encode_record("k1", "v1")
    b2 = bytearray(encode_record("k2", "v2"))
    b2[-1] ^= 0x01
    seg_path.write_bytes(b1 + bytes(b2))

    seg = Segment(seg_path, 1)
    with pytest.raises(CorruptSegmentError) as exc_info:
        list(seg.scan())
    assert exc_info.value.path == seg_path
    assert exc_info.value.offset == len(b1)
    assert "000001.seg" in str(exc_info.value)
    assert str(len(b1)) in str(exc_info.value)
    seg.close()


def test_index_operations_and_ordering() -> None:
    idx = Index()
    assert len(idx) == 0
    assert idx.tombstone_count() == 0

    idx.put("a", Location(1, 0), tombstone=False)
    idx.put("b", Location(1, 20), tombstone=False)
    idx.put("c", Location(2, 0), tombstone=False)
    assert idx.live_keys() == ["a", "b", "c"]
    assert len(idx) == 3

    idx.put("a", Location(2, 30), tombstone=False)
    assert idx.live_keys() == ["b", "c", "a"]

    idx.put("b", Location(2, 50), tombstone=True)
    assert idx.get("b") is None
    assert idx.live_keys() == ["c", "a"]
    assert len(idx) == 2
    assert idx.tombstone_count() == 1


def test_store_basic_crud_and_persistence(tmp_path: pathlib.Path) -> None:
    with KVStore(tmp_path) as store:
        store.set("alpha", "1")
        store.set("beta", "")
        assert store.get("alpha") == "1"
        assert store.get("beta") == ""
        assert store.get("gamma") is None
        assert store.keys() == ["alpha", "beta"]

    with KVStore(tmp_path) as store2:
        assert store2.get("alpha") == "1"
        assert store2.get("beta") == ""
        assert store2.keys() == ["alpha", "beta"]


def test_store_delete_semantics_and_noop(tmp_path: pathlib.Path) -> None:
    with KVStore(tmp_path) as store:
        assert store.delete("missing") is False
        assert store.stats().total_records == 0
        assert store.stats().bytes_on_disk == 0

        store.set("k", "v")
        bytes_after_set = store.stats().bytes_on_disk
        assert store.delete("k") is True
        assert store.get("k") is None
        bytes_after_del = store.stats().bytes_on_disk
        assert bytes_after_del > bytes_after_set

        assert store.delete("k") is False
        assert store.stats().bytes_on_disk == bytes_after_del
        assert store.stats().total_records == 2


def test_store_empty_string_value_vs_tombstone_recovery(tmp_path: pathlib.Path) -> None:
    with KVStore(tmp_path) as store:
        store.set("empty", "")
        store.set("deleted", "temp")
        store.delete("deleted")

    with KVStore(tmp_path) as reopened:
        assert reopened.get("empty") == ""
        assert reopened.get("deleted") is None
        assert reopened.keys() == ["empty"]
        st = reopened.stats()
        assert st.live_keys == 1
        assert st.tombstones == 1
        assert st.total_records == 3
        assert st.dead_records == 1


def test_store_validation_errors(tmp_path: pathlib.Path) -> None:
    with pytest.raises(ValueError):
        KVStore(tmp_path, max_segment_bytes=15)
    with pytest.raises(ValueError):
        KVStore(tmp_path, max_segment_bytes=True)

    with KVStore(tmp_path) as store:
        with pytest.raises(TypeError):
            store.set(b"k", "v")  # type: ignore[arg-type]
        with pytest.raises(TypeError):
            store.set("k", 123)  # type: ignore[arg-type]
        with pytest.raises(TypeError):
            store.get(b"k")  # type: ignore[arg-type]
        with pytest.raises(TypeError):
            store.delete(b"k")  # type: ignore[arg-type]
        with pytest.raises(ValueError):
            store.set("", "v")
        with pytest.raises(ValueError):
            store.set("汉" * 40000, "v")
        assert store.stats().bytes_on_disk == 0


def test_store_closed_operations_raise_value_error(tmp_path: pathlib.Path) -> None:
    store = KVStore(tmp_path)
    store.set("a", "1")
    store.close()
    store.close()  # idempotent

    with pytest.raises(ValueError):
        store.get("a")
    with pytest.raises(ValueError):
        store.set("b", "2")
    with pytest.raises(ValueError):
        store.delete("a")
    with pytest.raises(ValueError):
        store.keys()
    with pytest.raises(ValueError):
        store.stats()
    with pytest.raises(ValueError):
        compact(store)


def test_store_rollover_exact_fit_and_exceed(tmp_path: pathlib.Path) -> None:
    # Record "a" -> "1" is 15 + 1 + 1 = 17 bytes. Two records = 34 bytes.
    with KVStore(tmp_path, max_segment_bytes=34) as store:
        store.set("a", "1")
        store.set("b", "2")
        assert store.stats().segment_count == 1
        assert store.stats().bytes_on_disk == 34

        store.set("c", "3")
        assert store.stats().segment_count == 2
        assert (tmp_path / "000001.seg").exists()
        assert (tmp_path / "000002.seg").exists()


def test_store_oversized_record_in_empty_segment(tmp_path: pathlib.Path) -> None:
    with KVStore(tmp_path, max_segment_bytes=16) as store:
        store.set("big_key", "big_value_exceeding_16_bytes")
        assert store.stats().segment_count == 1
        assert store.get("big_key") == "big_value_exceeding_16_bytes"

        store.set("second", "record")
        assert store.stats().segment_count == 2


def test_store_ignores_non_matching_files(tmp_path: pathlib.Path) -> None:
    (tmp_path / "000003.seg.tmp").write_bytes(b"corrupt garbage")
    (tmp_path / "notes.txt").write_bytes(b"hello")
    (tmp_path / "123.seg").write_bytes(b"short id")

    with KVStore(tmp_path) as store:
        store.set("a", "1")
        st = store.stats()
        assert st.segment_count == 1
        assert st.live_keys == 1


def test_store_recovery_with_truncated_tail_and_stats(tmp_path: pathlib.Path) -> None:
    with KVStore(tmp_path) as store:
        store.set("a", "1")
        valid_size = store.stats().bytes_on_disk

    seg_file = tmp_path / "000001.seg"
    partial = encode_record("b", "unflushed_value")[:10]
    with seg_file.open("ab") as f:
        f.write(partial)

    with KVStore(tmp_path) as store:
        assert store.get("a") == "1"
        assert store.get("b") is None
        st = store.stats()
        assert st.live_keys == 1
        assert st.total_records == 1
        assert st.bytes_on_disk == valid_size + len(partial)


def test_store_keys_ordering_across_updates_and_segments(tmp_path: pathlib.Path) -> None:
    with KVStore(tmp_path, max_segment_bytes=25) as store:
        store.set("k1", "v1")
        store.set("k2", "v2")
        store.set("k3", "v3")
        assert store.keys() == ["k1", "k2", "k3"]

        store.set("k1", "v1_new")
        assert store.keys() == ["k2", "k3", "k1"]

        store.delete("k3")
        assert store.keys() == ["k2", "k1"]

        store.set("k3", "v3_reborn")
        assert store.keys() == ["k2", "k1", "k3"]


def test_compaction_reclaims_space_and_preserves_order(tmp_path: pathlib.Path) -> None:
    with KVStore(tmp_path, max_segment_bytes=36) as store:
        store.set("a", "1")
        store.set("b", "2")
        store.set("c", "3")
        store.set("a", "1_updated")
        store.delete("b")

        order_before = store.keys()
        stats_before = store.stats()
        assert stats_before.segment_count >= 2
        assert stats_before.tombstones == 1
        assert stats_before.dead_records == 2

        res = compact(store)
        assert res.segments_removed == stats_before.segment_count
        assert res.records_written == 2
        assert res.records_dropped == 3
        assert res.bytes_reclaimed > 0

        assert store.keys() == order_before
        assert store.get("a") == "1_updated"
        assert store.get("b") is None
        assert store.get("c") == "3"

        stats_after = store.stats()
        assert stats_after.segment_count == 1
        assert stats_after.live_keys == 2
        assert stats_after.tombstones == 0
        assert stats_after.dead_records == 0
        assert stats_after.total_records == 2

        store.set("d", "4")
        assert store.get("d") == "4"
        assert store.keys() == ["c", "a", "d"]


def test_compaction_on_empty_store(tmp_path: pathlib.Path) -> None:
    with KVStore(tmp_path) as store:
        store.set("x", "1")
        store.delete("x")
        res = compact(store)
        assert res.segments_removed == 1
        assert res.records_written == 0
        assert res.records_dropped == 2
        assert (tmp_path / "000002.seg").exists()
        assert not (tmp_path / "000001.seg").exists()
        assert store.stats().segment_count == 1
        assert store.stats().bytes_on_disk == 0

        store.set("y", "2")
        assert store.get("y") == "2"


def test_cli_round_trip(tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = str(tmp_path)
    assert main([root, "set", "a", "1"]) == 0
    assert capsys.readouterr() == ("", "")

    assert main([root, "get", "a"]) == 0
    assert capsys.readouterr() == ("1\n", "")

    assert main([root, "get", "zz"]) == 1
    assert capsys.readouterr() == ("", "")

    assert main([root, "list"]) == 0
    assert capsys.readouterr() == ("a\n", "")

    assert main([root, "stats"]) == 0
    out, err = capsys.readouterr()
    assert err == ""
    assert out == (
        "live_keys=1 tombstones=0 total_records=1 "
        "dead_records=0 segment_count=1 bytes_on_disk=17\n"
    )


def test_cli_delete_and_compact(
    tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = str(tmp_path)
    assert main([root, "set", "k1", "v1"]) == 0
    assert main([root, "set", "k2", "v2"]) == 0
    assert main([root, "delete", "k1"]) == 0
    assert capsys.readouterr() == ("", "")

    assert main([root, "delete", "k1"]) == 1
    assert capsys.readouterr() == ("", "")

    assert main([root, "compact"]) == 0
    out, err = capsys.readouterr()
    assert err == ""
    assert out == "removed=1 written=1 dropped=2 reclaimed=36\n"


def test_cli_error_exit_codes(
    tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = str(tmp_path)
    assert main([root, "unknown_cmd"]) == 2
    out, err = capsys.readouterr()
    assert out == ""
    assert err != ""

    assert main([root, "set", "only_one_arg"]) == 2
    out, err = capsys.readouterr()
    assert out == ""
    assert err != ""

    assert main(["--max-segment-bytes", "0", root, "stats"]) == 2
    out, err = capsys.readouterr()
    assert out == ""
    assert err != ""

    assert main(["--max-segment-bytes", "10", root, "stats"]) == 2
    out, err = capsys.readouterr()
    assert out == ""
    assert err != ""

    assert main([root, "set", "", "val"]) == 2
    out, err = capsys.readouterr()
    assert out == ""
    assert err != ""


def test_cli_corrupt_segment_exit_code_3(
    tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = str(tmp_path)
    assert main([root, "set", "a", "1"]) == 0
    capsys.readouterr()

    seg_file = tmp_path / "000001.seg"
    data = bytearray(seg_file.read_bytes())
    data[-1] ^= 0xFF
    seg_file.write_bytes(bytes(data))

    assert main([root, "get", "a"]) == 3
    out, err = capsys.readouterr()
    assert out == ""
    assert "000001.seg" in err


def test_cli_subprocess_execution(tmp_path: pathlib.Path) -> None:
    proc = subprocess.run(
        [sys.executable, "-m", "kvstore", str(tmp_path), "set", "hello", "world"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0
    assert proc.stdout == ""

    proc2 = subprocess.run(
        [sys.executable, "-m", "kvstore", str(tmp_path), "get", "hello"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc2.returncode == 0
    assert proc2.stdout == "world\n"


def test_record_max_key_len_boundary() -> None:
    max_key = "k" * 65535
    blob = encode_record(max_key, "v")
    k, v, sz = decode_record(blob)
    assert k == max_key
    assert v == "v"
    assert sz == 15 + 65535 + 1


def test_segment_multiple_corruptions_reports_first_offset(tmp_path: pathlib.Path) -> None:
    seg_path = tmp_path / "000001.seg"
    b1 = encode_record("ok", "1")
    b2 = bytearray(encode_record("bad", "2"))
    b2[0] = ord("X")
    b3 = encode_record("ok2", "3")
    seg_path.write_bytes(b1 + bytes(b2) + b3)

    seg = Segment(seg_path, 1)
    with pytest.raises(CorruptSegmentError) as exc_info:
        list(seg.scan())
    assert exc_info.value.offset == len(b1)
    seg.close()


def test_compaction_persists_across_reopen(tmp_path: pathlib.Path) -> None:
    with KVStore(tmp_path, max_segment_bytes=32) as store:
        for i in range(6):
            store.set(f"k{i}", f"v{i}")
        store.delete("k1")
        store.delete("k3")
        store.set("k0", "v0_new")
        expected_keys = store.keys()
        compact(store)

    with KVStore(tmp_path, max_segment_bytes=32) as reopened:
        assert reopened.keys() == expected_keys
        assert reopened.get("k0") == "v0_new"
        assert reopened.get("k1") is None
        assert reopened.get("k2") == "v2"
        assert reopened.stats().segment_count == 1
        assert reopened.stats().tombstones == 0
        assert reopened.stats().dead_records == 0


def test_cli_global_flag_positions(
    tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = str(tmp_path)
    assert main(["--max-segment-bytes", "32", root, "set", "k1", "v1"]) == 0
    assert main([root, "--max-segment-bytes=32", "set", "k2", "v2"]) == 0
    assert main([root, "set", "k3", "v3", "--max-segment-bytes", "32"]) == 0
    capsys.readouterr()

    with KVStore(tmp_path) as store:
        assert store.stats().segment_count >= 2


def test_cli_missing_flag_value_exits_2(
    tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = str(tmp_path)
    assert main([root, "stats", "--max-segment-bytes"]) == 2
    out, err = capsys.readouterr()
    assert out == ""
    assert err != ""


def test_store_creates_nested_root_directory(tmp_path: pathlib.Path) -> None:
    nested = tmp_path / "a" / "b" / "c"
    with KVStore(nested) as store:
        store.set("x", "y")
    assert (nested / "000001.seg").is_file()

