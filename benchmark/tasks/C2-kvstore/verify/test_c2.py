"""Hidden verification suite for task C2. Not visible to the model under test."""
import importlib
import struct
import subprocess
import sys
import zlib
from pathlib import Path

import pytest

_IGNORED_DIRS = {"__pycache__", "_verify", ".pytest_cache", ".git", ".ruff_cache", ".mypy_cache"}

HEADER = 15
MAGIC = b"KVR1"


@pytest.fixture(scope="module")
def kv():
    sys.path.insert(0, ".")
    return importlib.import_module("kvstore")


@pytest.fixture
def store_factory(kv, tmp_path):
    made = []

    def make(sub="db", **kwargs):
        store = kv.KVStore(tmp_path / sub, **kwargs)
        made.append(store)
        return store

    yield make
    for store in made:
        try:
            store.close()
        except Exception:  # noqa: BLE001 - fixture teardown must not mask failures
            pass


def cli(root, *args, timeout=60):
    return subprocess.run(
        [sys.executable, "-m", "kvstore", str(root), *args],
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd=".",
    )


def hand_record(key: bytes, value: bytes, flags: int = 0x00, *, magic=MAGIC, crc=None,
                key_len=None, value_len=None) -> bytes:
    """Build a record by hand so the suite does not depend on encode_record."""
    if crc is None:
        crc = zlib.crc32(key + value)
    header = struct.pack(
        ">4sBHII",
        magic,
        flags,
        len(key) if key_len is None else key_len,
        len(value) if value_len is None else value_len,
        crc,
    )
    return header + key + value


# --------------------------------------------------------------------------- #
# 1. record codec
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize(
    "key,value",
    [
        ("a", "1"),
        ("key", "value"),
        ("k", ""),
        ("x" * 100, "y" * 200),
        ("中文", "值"),
        ("emoji", "\U0001f600"),
        ("tab\tkey", "nl\nvalue"),
        ("quote\"key", "back\\slash"),
        ("\x00nul", "\x00nul"),
        ("a", "z" * 5000),
    ],
)
def test_record_round_trip(kv, key, value):
    blob = kv.encode_record(key, value)
    assert kv.decode_record(blob) == (key, value, len(blob))


def test_record_total_size_formula(kv):
    key, value = "abc", "defgh"
    blob = kv.encode_record(key, value)
    assert len(blob) == HEADER + len(key.encode()) + len(value.encode())


def test_record_header_is_fifteen_bytes(kv):
    assert len(kv.encode_record("a", "")) == HEADER + 1


def test_record_magic(kv):
    assert kv.encode_record("a", "1")[:4] == MAGIC


def test_record_flags_value(kv):
    assert kv.encode_record("a", "1")[4] == 0x00


def test_record_flags_tombstone(kv):
    assert kv.encode_record("a", None)[4] == 0x01


def test_record_lengths_big_endian(kv):
    blob = kv.encode_record("ab", "cde")
    key_len, value_len = struct.unpack_from(">HI", blob, 5)
    assert (key_len, value_len) == (2, 3)


def test_record_crc_covers_body_only(kv):
    blob = kv.encode_record("ab", "cde")
    crc = struct.unpack_from(">I", blob, 11)[0]
    assert crc == zlib.crc32(b"abcde")


def test_record_crc_is_not_over_whole_record(kv):
    blob = kv.encode_record("ab", "cde")
    crc = struct.unpack_from(">I", blob, 11)[0]
    assert crc != zlib.crc32(blob[:11] + b"abcde")


def test_tombstone_value_len_zero(kv):
    blob = kv.encode_record("a", None)
    assert struct.unpack_from(">I", blob, 7)[0] == 0


def test_tombstone_has_no_value_bytes(kv):
    assert len(kv.encode_record("key", None)) == HEADER + 3


def test_tombstone_decodes_none(kv):
    assert kv.decode_record(kv.encode_record("a", None))[1] is None


def test_empty_value_decodes_empty_string(kv):
    assert kv.decode_record(kv.encode_record("a", ""))[1] == ""


def test_empty_value_and_tombstone_differ_in_bytes(kv):
    assert kv.encode_record("a", "") != kv.encode_record("a", None)


def test_empty_value_and_tombstone_same_length(kv):
    assert len(kv.encode_record("a", "")) == len(kv.encode_record("a", None))


def test_decode_at_offset(kv):
    first = kv.encode_record("a", "1")
    second = kv.encode_record("bb", "22")
    key, value, size = kv.decode_record(first + second, len(first))
    assert (key, value, size) == ("bb", "22", len(second))


def test_decode_ignores_trailing_bytes(kv):
    blob = kv.encode_record("a", "1")
    assert kv.decode_record(blob + b"junk") == ("a", "1", len(blob))


@pytest.mark.parametrize("cut", [0, 1, 5, 14])
def test_decode_short_header_incomplete(kv, cut):
    with pytest.raises(kv.IncompleteRecordError):
        kv.decode_record(kv.encode_record("abc", "defg")[:cut])


@pytest.mark.parametrize("missing", [1, 2, 6])
def test_decode_short_body_incomplete(kv, missing):
    blob = kv.encode_record("abc", "defghij")
    with pytest.raises(kv.IncompleteRecordError):
        kv.decode_record(blob[:-missing])


def test_decode_bad_magic(kv):
    with pytest.raises(kv.CorruptRecordError):
        kv.decode_record(hand_record(b"a", b"1", magic=b"XXXX"))


@pytest.mark.parametrize("flags", [0x02, 0x03, 0x7F, 0xFF])
def test_decode_unknown_flags(kv, flags):
    with pytest.raises(kv.CorruptRecordError):
        kv.decode_record(hand_record(b"a", b"1", flags=flags))


def test_decode_zero_key_len(kv):
    with pytest.raises(kv.CorruptRecordError):
        kv.decode_record(hand_record(b"", b"1"))


def test_decode_tombstone_with_value(kv):
    blob = hand_record(b"a", b"", flags=0x01, value_len=3)
    with pytest.raises(kv.CorruptRecordError):
        kv.decode_record(blob + b"bad")


def test_decode_crc_mismatch(kv):
    with pytest.raises(kv.CorruptRecordError):
        kv.decode_record(hand_record(b"a", b"1", crc=12345))


def test_decode_bad_utf8_key(kv):
    with pytest.raises(kv.CorruptRecordError):
        kv.decode_record(hand_record(b"\xff\xfe", b"1"))


def test_decode_bad_utf8_value(kv):
    with pytest.raises(kv.CorruptRecordError):
        kv.decode_record(hand_record(b"a", b"\xff\xfe"))


def test_structural_check_precedes_crc(kv):
    """Bad magic plus a bad CRC must report the structural problem, not the CRC."""
    blob = hand_record(b"a", b"1", magic=b"ZZZZ", crc=999)
    with pytest.raises(kv.CorruptRecordError) as info:
        kv.decode_record(blob)
    assert "crc" not in str(info.value).lower()


def test_incomplete_beats_corrupt_for_short_buffer(kv):
    """A truncated buffer is incomplete even if the visible header is nonsense."""
    with pytest.raises(kv.IncompleteRecordError):
        kv.decode_record(b"\xff\xff\xff")


def test_encode_rejects_empty_key(kv):
    with pytest.raises(ValueError):
        kv.encode_record("", "v")


def test_encode_rejects_oversize_key(kv):
    with pytest.raises(ValueError):
        kv.encode_record("a" * 70000, "v")


def test_encode_rejects_oversize_multibyte_key(kv):
    with pytest.raises(ValueError):
        kv.encode_record("中" * 30000, "v")


def test_encode_accepts_max_key(kv):
    key = "a" * 65535
    assert kv.decode_record(kv.encode_record(key, "v"))[0] == key


# --------------------------------------------------------------------------- #
# 2. segment
# --------------------------------------------------------------------------- #

def test_segment_name_padding(kv, tmp_path):
    with kv.KVStore(tmp_path / "db") as store:
        store.set("a", "1")
    assert (tmp_path / "db" / "000001.seg").is_file()


def test_segment_ids_start_at_one(kv, tmp_path):
    with kv.KVStore(tmp_path / "db") as store:
        store.set("a", "1")
    names = sorted(p.name for p in (tmp_path / "db").glob("*.seg"))
    assert names == ["000001.seg"]


def test_segment_append_returns_offset(kv, tmp_path):
    seg = kv.Segment(tmp_path / "000001.seg", 1)
    first = kv.encode_record("a", "1")
    assert seg.append(first) == 0
    assert seg.append(kv.encode_record("b", "2")) == len(first)
    seg.close()


def test_segment_size_tracks_file(kv, tmp_path):
    seg = kv.Segment(tmp_path / "000001.seg", 1)
    blob = kv.encode_record("a", "1")
    seg.append(blob)
    assert seg.size == len(blob)
    seg.close()


def test_segment_seg_id_property(kv, tmp_path):
    seg = kv.Segment(tmp_path / "000007.seg", 7)
    assert seg.seg_id == 7
    seg.close()


def test_segment_scan_yields_offsets(kv, tmp_path):
    seg = kv.Segment(tmp_path / "000001.seg", 1)
    first = kv.encode_record("a", "1")
    seg.append(first)
    seg.append(kv.encode_record("b", "2"))
    seg.close()
    seg2 = kv.Segment(tmp_path / "000001.seg", 1)
    assert [(k, v, o) for k, v, o in seg2.scan()] == [
        ("a", "1", 0),
        ("b", "2", len(first)),
    ]
    seg2.close()


def test_segment_scan_empty_file(kv, tmp_path):
    seg = kv.Segment(tmp_path / "000001.seg", 1)
    assert list(seg.scan()) == []
    seg.close()


@pytest.mark.parametrize("missing", [1, 3, 9])
def test_segment_scan_stops_at_truncated_tail(kv, tmp_path, missing):
    path = tmp_path / "000001.seg"
    good = kv.encode_record("a", "1")
    partial = kv.encode_record("b", "longer value")[:-missing]
    path.write_bytes(good + partial)
    seg = kv.Segment(path, 1)
    assert [k for k, _, _ in seg.scan()] == ["a"]
    seg.close()


def test_segment_scan_stops_at_short_header(kv, tmp_path):
    path = tmp_path / "000001.seg"
    path.write_bytes(kv.encode_record("a", "1") + b"\x00\x01\x02")
    seg = kv.Segment(path, 1)
    assert [k for k, _, _ in seg.scan()] == ["a"]
    seg.close()


def test_segment_scan_raises_on_crc_damage(kv, tmp_path):
    path = tmp_path / "000001.seg"
    data = bytearray(kv.encode_record("a", "1"))
    data[-1] ^= 0xFF
    path.write_bytes(bytes(data))
    seg = kv.Segment(path, 1)
    with pytest.raises(kv.CorruptSegmentError):
        list(seg.scan())
    seg.close()


def test_crc_damage_on_last_record_is_not_truncation(kv, tmp_path):
    """The decisive case: all bytes present, checksum wrong, last record."""
    path = tmp_path / "000001.seg"
    good = kv.encode_record("a", "1")
    bad = bytearray(kv.encode_record("b", "2"))
    bad[-1] ^= 0xFF
    path.write_bytes(good + bytes(bad))
    seg = kv.Segment(path, 1)
    with pytest.raises(kv.CorruptSegmentError):
        list(seg.scan())
    seg.close()


def test_segment_scan_raises_on_bad_magic(kv, tmp_path):
    path = tmp_path / "000001.seg"
    path.write_bytes(hand_record(b"a", b"1", magic=b"NOPE"))
    seg = kv.Segment(path, 1)
    with pytest.raises(kv.CorruptSegmentError):
        list(seg.scan())
    seg.close()


def test_corrupt_segment_error_offset(kv, tmp_path):
    path = tmp_path / "000001.seg"
    good = kv.encode_record("a", "1")
    bad = bytearray(kv.encode_record("b", "2"))
    bad[-1] ^= 0xFF
    path.write_bytes(good + bytes(bad))
    seg = kv.Segment(path, 1)
    with pytest.raises(kv.CorruptSegmentError) as info:
        list(seg.scan())
    assert info.value.offset == len(good)
    seg.close()


def test_corrupt_segment_error_path_attribute(kv, tmp_path):
    path = tmp_path / "000001.seg"
    path.write_bytes(hand_record(b"a", b"1", crc=7))
    seg = kv.Segment(path, 1)
    with pytest.raises(kv.CorruptSegmentError) as info:
        list(seg.scan())
    assert Path(info.value.path).name == "000001.seg"
    seg.close()


def test_corrupt_segment_error_str_has_name_and_offset(kv, tmp_path):
    path = tmp_path / "000004.seg"
    path.write_bytes(hand_record(b"a", b"1", crc=7))
    seg = kv.Segment(path, 4)
    with pytest.raises(kv.CorruptSegmentError) as info:
        list(seg.scan())
    text = str(info.value)
    assert "000004.seg" in text and "0" in text
    seg.close()


# --------------------------------------------------------------------------- #
# 3. index
# --------------------------------------------------------------------------- #

def test_location_is_frozen(kv):
    loc = kv.Location(1, 0)
    with pytest.raises(Exception):
        loc.seg_id = 2


def test_location_fields(kv):
    loc = kv.Location(3, 42)
    assert (loc.seg_id, loc.offset) == (3, 42)


def test_location_equality(kv):
    assert kv.Location(1, 2) == kv.Location(1, 2)


def test_index_put_get(kv):
    index = kv.Index()
    index.put("a", kv.Location(1, 0), tombstone=False)
    assert index.get("a") == kv.Location(1, 0)


def test_index_get_missing(kv):
    assert kv.Index().get("nope") is None


def test_index_tombstone_hides_key(kv):
    index = kv.Index()
    index.put("a", kv.Location(1, 0), tombstone=False)
    index.put("a", kv.Location(1, 20), tombstone=True)
    assert index.get("a") is None


def test_index_resurrect_after_tombstone(kv):
    index = kv.Index()
    index.put("a", kv.Location(1, 0), tombstone=True)
    index.put("a", kv.Location(1, 20), tombstone=False)
    assert index.get("a") == kv.Location(1, 20)


def test_index_len_counts_live_only(kv):
    index = kv.Index()
    index.put("a", kv.Location(1, 0), tombstone=False)
    index.put("b", kv.Location(1, 20), tombstone=True)
    assert len(index) == 1


def test_index_tombstone_count(kv):
    index = kv.Index()
    index.put("a", kv.Location(1, 0), tombstone=True)
    index.put("b", kv.Location(1, 20), tombstone=True)
    index.put("c", kv.Location(1, 40), tombstone=False)
    assert index.tombstone_count() == 2


def test_index_live_keys_order_by_segment_then_offset(kv):
    index = kv.Index()
    index.put("third", kv.Location(2, 5), tombstone=False)
    index.put("first", kv.Location(1, 0), tombstone=False)
    index.put("second", kv.Location(1, 99), tombstone=False)
    assert index.live_keys() == ["first", "second", "third"]


def test_index_live_keys_excludes_tombstones(kv):
    index = kv.Index()
    index.put("a", kv.Location(1, 0), tombstone=False)
    index.put("b", kv.Location(1, 10), tombstone=True)
    assert index.live_keys() == ["a"]


def test_index_rewrite_moves_key_to_end(kv):
    index = kv.Index()
    index.put("a", kv.Location(1, 0), tombstone=False)
    index.put("b", kv.Location(1, 10), tombstone=False)
    index.put("a", kv.Location(1, 20), tombstone=False)
    assert index.live_keys() == ["b", "a"]


# --------------------------------------------------------------------------- #
# 4. store basics
# --------------------------------------------------------------------------- #

def test_store_creates_root(kv, tmp_path):
    root = tmp_path / "deep" / "nested"
    with kv.KVStore(root):
        pass
    assert root.is_dir()


def test_set_get(store_factory):
    store = store_factory()
    store.set("a", "1")
    assert store.get("a") == "1"


def test_get_absent_none(store_factory):
    assert store_factory().get("missing") is None


def test_overwrite_returns_newest(store_factory):
    store = store_factory()
    store.set("a", "1")
    store.set("a", "2")
    assert store.get("a") == "2"


@pytest.mark.parametrize("value", ["", "x", "x" * 1000, "中文值", "\n\t", "\x00"])
def test_value_round_trip(store_factory, value):
    store = store_factory()
    store.set("k", value)
    assert store.get("k") == value


def test_empty_value_is_not_none(store_factory):
    store = store_factory()
    store.set("a", "")
    got = store.get("a")
    assert got == "" and got is not None


def test_empty_value_key_is_live(store_factory):
    store = store_factory()
    store.set("a", "")
    assert store.keys() == ["a"]


def test_delete_live_returns_true(store_factory):
    store = store_factory()
    store.set("a", "1")
    assert store.delete("a") is True


def test_delete_makes_get_none(store_factory):
    store = store_factory()
    store.set("a", "1")
    store.delete("a")
    assert store.get("a") is None


def test_delete_absent_returns_false(store_factory):
    assert store_factory().delete("ghost") is False


def test_delete_absent_writes_nothing(store_factory):
    store = store_factory()
    store.set("a", "1")
    before = store.stats()
    assert store.delete("ghost") is False
    after = store.stats()
    assert after.total_records == before.total_records
    assert after.bytes_on_disk == before.bytes_on_disk


def test_double_delete_returns_false(store_factory):
    store = store_factory()
    store.set("a", "1")
    store.delete("a")
    assert store.delete("a") is False


def test_double_delete_writes_nothing(store_factory):
    store = store_factory()
    store.set("a", "1")
    store.delete("a")
    before = store.stats().total_records
    store.delete("a")
    assert store.stats().total_records == before


def test_delete_after_empty_value(store_factory):
    """An empty value is live, so deleting it must succeed."""
    store = store_factory()
    store.set("a", "")
    assert store.delete("a") is True


def test_resurrect_after_delete(store_factory):
    store = store_factory()
    store.set("a", "1")
    store.delete("a")
    store.set("a", "2")
    assert store.get("a") == "2"
    assert store.keys() == ["a"]


def test_keys_empty_store(store_factory):
    assert store_factory().keys() == []


def test_keys_insertion_order(store_factory):
    store = store_factory()
    for key in ("c", "a", "b"):
        store.set(key, "v")
    assert store.keys() == ["c", "a", "b"]


def test_keys_rewrite_moves_to_end(store_factory):
    store = store_factory()
    for key in ("a", "b", "c"):
        store.set(key, "v")
    store.set("a", "again")
    assert store.keys() == ["b", "c", "a"]


def test_keys_not_sorted(store_factory):
    store = store_factory()
    for key in ("z", "y", "x"):
        store.set(key, "v")
    assert store.keys() == ["z", "y", "x"]


def test_keys_excludes_deleted(store_factory):
    store = store_factory()
    store.set("a", "1")
    store.set("b", "2")
    store.delete("a")
    assert store.keys() == ["b"]


def test_context_manager_returns_store(kv, tmp_path):
    with kv.KVStore(tmp_path / "db") as store:
        assert isinstance(store, kv.KVStore)


def test_close_then_use_raises(kv, tmp_path):
    store = kv.KVStore(tmp_path / "db")
    store.close()
    with pytest.raises(ValueError):
        store.get("a")


@pytest.mark.parametrize("method,args", [("set", ("a", "1")), ("delete", ("a",)),
                                        ("keys", ()), ("stats", ())])
def test_closed_store_rejects_every_operation(kv, tmp_path, method, args):
    store = kv.KVStore(tmp_path / "db")
    store.close()
    with pytest.raises(ValueError):
        getattr(store, method)(*args)


def test_close_idempotent(kv, tmp_path):
    store = kv.KVStore(tmp_path / "db")
    store.close()
    store.close()


def test_context_manager_closes(kv, tmp_path):
    with kv.KVStore(tmp_path / "db") as store:
        store.set("a", "1")
    with pytest.raises(ValueError):
        store.get("a")


# --------------------------------------------------------------------------- #
# 5. reopen and recovery
# --------------------------------------------------------------------------- #

def test_reopen_sees_values(kv, tmp_path):
    with kv.KVStore(tmp_path / "db") as store:
        store.set("a", "1")
        store.set("b", "2")
    with kv.KVStore(tmp_path / "db") as store:
        assert (store.get("a"), store.get("b")) == ("1", "2")


def test_reopen_sees_newest_value(kv, tmp_path):
    with kv.KVStore(tmp_path / "db") as store:
        store.set("a", "old")
        store.set("a", "new")
    with kv.KVStore(tmp_path / "db") as store:
        assert store.get("a") == "new"


def test_reopen_respects_tombstone(kv, tmp_path):
    with kv.KVStore(tmp_path / "db") as store:
        store.set("a", "1")
        store.delete("a")
    with kv.KVStore(tmp_path / "db") as store:
        assert store.get("a") is None and store.keys() == []


def test_reopen_respects_resurrection(kv, tmp_path):
    with kv.KVStore(tmp_path / "db") as store:
        store.set("a", "1")
        store.delete("a")
        store.set("a", "2")
    with kv.KVStore(tmp_path / "db") as store:
        assert store.get("a") == "2"


def test_reopen_preserves_keys_order(kv, tmp_path):
    with kv.KVStore(tmp_path / "db") as store:
        for key in ("q", "w", "e"):
            store.set(key, "v")
        store.set("q", "again")
        expected = store.keys()
    with kv.KVStore(tmp_path / "db") as store:
        assert store.keys() == expected


def test_reopen_across_segments_last_wins(kv, tmp_path):
    with kv.KVStore(tmp_path / "db", max_segment_bytes=20) as store:
        for i in range(6):
            store.set("a", f"v{i}")
    with kv.KVStore(tmp_path / "db") as store:
        assert store.get("a") == "v5"


def test_reopen_ignores_truncated_tail(kv, tmp_path):
    root = tmp_path / "db"
    with kv.KVStore(root) as store:
        store.set("a", "1")
    seg = root / "000001.seg"
    seg.write_bytes(seg.read_bytes() + kv.encode_record("b", "longer")[:-4])
    with kv.KVStore(root) as store:
        assert store.keys() == ["a"]


def test_writes_after_truncated_tail_recovery(kv, tmp_path):
    root = tmp_path / "db"
    with kv.KVStore(root) as store:
        store.set("a", "1")
    seg = root / "000001.seg"
    seg.write_bytes(seg.read_bytes() + kv.encode_record("b", "longer")[:-4])
    with kv.KVStore(root) as store:
        store.set("c", "3")
        assert store.get("c") == "3"


def test_reopen_raises_on_corruption(kv, tmp_path):
    root = tmp_path / "db"
    with kv.KVStore(root) as store:
        store.set("a", "1")
    seg = root / "000001.seg"
    data = bytearray(seg.read_bytes())
    data[-1] ^= 0xFF
    seg.write_bytes(bytes(data))
    with pytest.raises(kv.CorruptSegmentError):
        kv.KVStore(root)


def test_recovery_scans_segments_in_id_order(kv, tmp_path):
    root = tmp_path / "db"
    root.mkdir()
    (root / "000001.seg").write_bytes(kv.encode_record("a", "old"))
    (root / "000002.seg").write_bytes(kv.encode_record("a", "new"))
    with kv.KVStore(root) as store:
        assert store.get("a") == "new"


def test_recovery_uses_numeric_not_lexical_order(kv, tmp_path):
    root = tmp_path / "db"
    root.mkdir()
    (root / "000002.seg").write_bytes(kv.encode_record("a", "second"))
    (root / "000010.seg").write_bytes(kv.encode_record("a", "tenth"))
    with kv.KVStore(root) as store:
        assert store.get("a") == "tenth"


def test_active_segment_is_highest_id(kv, tmp_path):
    root = tmp_path / "db"
    root.mkdir()
    (root / "000001.seg").write_bytes(kv.encode_record("a", "1"))
    (root / "000005.seg").write_bytes(kv.encode_record("b", "2"))
    with kv.KVStore(root, max_segment_bytes=100000) as store:
        store.set("c", "3")
        assert sorted(p.name for p in root.glob("*.seg"))[-1] == "000005.seg"


@pytest.mark.parametrize("name", ["000003.seg.tmp", "notes.txt", "1.seg", "0000010.seg",
                                  "00001.seg", "abcdef.seg", "000002.SEG"])
def test_non_segment_names_ignored(kv, tmp_path, name):
    root = tmp_path / "db"
    root.mkdir()
    (root / name).write_bytes(b"total garbage not a record")
    with kv.KVStore(root) as store:
        store.set("a", "1")
        assert store.get("a") == "1"
        assert store.stats().segment_count == 1


def test_empty_root_creates_first_segment(kv, tmp_path):
    root = tmp_path / "db"
    with kv.KVStore(root) as store:
        store.set("a", "1")
    assert (root / "000001.seg").is_file()


# --------------------------------------------------------------------------- #
# 6. validation
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("key", [b"bytes", 1, 1.5, None, ["a"], {"a": 1}, ("a",)])
def test_set_rejects_non_str_key(store_factory, key):
    with pytest.raises(TypeError):
        store_factory().set(key, "1")


def test_set_rejects_bytes_key_without_decoding(store_factory):
    store = store_factory()
    with pytest.raises(TypeError):
        store.set(b"a", "1")
    assert store.keys() == []


@pytest.mark.parametrize("value", [b"bytes", 1, 1.5, None, ["a"], {"a": 1}])
def test_set_rejects_non_str_value(store_factory, value):
    with pytest.raises(TypeError):
        store_factory().set("a", value)


@pytest.mark.parametrize("key", [b"bytes", 1, None])
def test_get_rejects_non_str_key(store_factory, key):
    with pytest.raises(TypeError):
        store_factory().get(key)


@pytest.mark.parametrize("key", [b"bytes", 1, None])
def test_delete_rejects_non_str_key(store_factory, key):
    with pytest.raises(TypeError):
        store_factory().delete(key)


def test_empty_key_rejected(store_factory):
    with pytest.raises(ValueError):
        store_factory().set("", "1")


def test_oversize_ascii_key_rejected(store_factory):
    with pytest.raises(ValueError):
        store_factory().set("a" * 65536, "1")


def test_max_ascii_key_accepted(store_factory):
    store = store_factory()
    store.set("a" * 65535, "1")
    assert store.get("a" * 65535) == "1"


def test_key_limit_is_bytes_not_characters(store_factory):
    """40000 CJK characters is 120000 bytes, so it must be rejected."""
    with pytest.raises(ValueError):
        store_factory().set("中" * 40000, "1")


def test_multibyte_key_within_byte_limit_accepted(store_factory):
    key = "中" * 20000  # 60000 bytes, under the limit
    store = store_factory()
    store.set(key, "1")
    assert store.get(key) == "1"


def test_validation_happens_before_write(store_factory):
    store = store_factory()
    before = store.stats().bytes_on_disk
    with pytest.raises(ValueError):
        store.set("", "1")
    assert store.stats().bytes_on_disk == before


@pytest.mark.parametrize("bad", [0, 1, 15, -1])
def test_max_segment_bytes_minimum(kv, tmp_path, bad):
    with pytest.raises(ValueError):
        kv.KVStore(tmp_path / "db", max_segment_bytes=bad)


def test_max_segment_bytes_sixteen_ok(kv, tmp_path):
    with kv.KVStore(tmp_path / "db", max_segment_bytes=16) as store:
        store.set("a", "1")


# --------------------------------------------------------------------------- #
# 7. rollover
# --------------------------------------------------------------------------- #

def test_single_segment_when_small(store_factory):
    store = store_factory(max_segment_bytes=4096)
    for i in range(10):
        store.set(f"k{i}", "v")
    assert store.stats().segment_count == 1


def test_rollover_creates_second_segment(store_factory):
    store = store_factory(max_segment_bytes=40)
    store.set("a", "x" * 10)
    store.set("b", "y" * 10)
    assert store.stats().segment_count == 2


def test_rollover_exact_fit_stays(kv, tmp_path):
    """size + n == max is still a fit, because the test is strictly greater than."""
    root = tmp_path / "db"
    one = len(kv.encode_record("a", "1"))
    with kv.KVStore(root, max_segment_bytes=one * 2) as store:
        store.set("a", "1")
        store.set("b", "2")
        assert store.stats().segment_count == 1


def test_rollover_one_byte_over_splits(kv, tmp_path):
    root = tmp_path / "db"
    one = len(kv.encode_record("a", "1"))
    with kv.KVStore(root, max_segment_bytes=one * 2 - 1) as store:
        store.set("a", "1")
        store.set("b", "2")
        assert store.stats().segment_count == 2


def test_oversized_record_stored_in_empty_segment(store_factory):
    store = store_factory(max_segment_bytes=16)
    store.set("a", "z" * 500)
    assert store.get("a") == "z" * 500


def test_oversized_record_each_gets_own_segment(store_factory):
    store = store_factory(max_segment_bytes=16)
    store.set("a", "z" * 100)
    store.set("b", "y" * 100)
    assert store.stats().segment_count == 2


def test_oversized_records_readable_after_reopen(kv, tmp_path):
    root = tmp_path / "db"
    with kv.KVStore(root, max_segment_bytes=16) as store:
        store.set("a", "z" * 100)
        store.set("b", "y" * 100)
    with kv.KVStore(root) as store:
        assert (store.get("a"), store.get("b")) == ("z" * 100, "y" * 100)


def test_rollover_ids_are_consecutive(store_factory, tmp_path):
    store = store_factory(max_segment_bytes=20)
    for i in range(4):
        store.set(f"k{i}", "value")
    names = sorted(p.name for p in (tmp_path / "db").glob("*.seg"))
    assert names == [f"{i:06d}.seg" for i in range(1, len(names) + 1)]


def test_tombstone_also_rolls_over(store_factory):
    store = store_factory(max_segment_bytes=20)
    store.set("a", "1")
    store.delete("a")
    assert store.stats().segment_count >= 2


def test_keys_order_across_segments(store_factory):
    store = store_factory(max_segment_bytes=20)
    for key in ("a", "b", "c", "d"):
        store.set(key, "v")
    assert store.keys() == ["a", "b", "c", "d"]


# --------------------------------------------------------------------------- #
# 8. stats
# --------------------------------------------------------------------------- #

def test_stats_fresh_store(store_factory):
    stats = store_factory().stats()
    assert (stats.live_keys, stats.tombstones, stats.total_records) == (0, 0, 0)


def test_stats_live_keys(store_factory):
    store = store_factory()
    store.set("a", "1")
    store.set("b", "2")
    assert store.stats().live_keys == 2


def test_stats_counts_overwrite_as_dead(store_factory):
    store = store_factory()
    store.set("a", "1")
    store.set("a", "2")
    stats = store.stats()
    assert (stats.live_keys, stats.total_records, stats.dead_records) == (1, 2, 1)


def test_stats_newest_tombstone_not_dead(store_factory):
    store = store_factory()
    store.set("a", "1")
    store.delete("a")
    stats = store.stats()
    assert (stats.live_keys, stats.tombstones) == (0, 1)
    assert stats.dead_records == 1


def test_stats_dead_records_formula(store_factory):
    store = store_factory()
    store.set("a", "1")
    store.set("a", "2")
    store.set("b", "3")
    store.delete("b")
    stats = store.stats()
    assert stats.dead_records == stats.total_records - stats.live_keys - stats.tombstones


def test_stats_segment_count(kv, tmp_path):
    root = tmp_path / "db"
    with kv.KVStore(root, max_segment_bytes=20) as store:
        for key in ("a", "b", "c"):
            store.set(key, "v")
        on_disk = len(list(root.glob("*.seg")))
        assert on_disk >= 2
        assert store.stats().segment_count == on_disk


def test_stats_bytes_on_disk_matches_files(kv, tmp_path):
    root = tmp_path / "db"
    with kv.KVStore(root, max_segment_bytes=30) as store:
        for key in ("a", "b", "c"):
            store.set(key, "value")
        expected = sum(p.stat().st_size for p in root.glob("*.seg"))
        assert store.stats().bytes_on_disk == expected


def test_stats_bytes_includes_truncated_tail(kv, tmp_path):
    root = tmp_path / "db"
    with kv.KVStore(root) as store:
        store.set("a", "1")
    seg = root / "000001.seg"
    seg.write_bytes(seg.read_bytes() + b"\x00" * 7)
    with kv.KVStore(root) as store:
        assert store.stats().bytes_on_disk == seg.stat().st_size


def test_stats_field_order(kv, tmp_path):
    with kv.KVStore(tmp_path / "db") as store:
        stats = store.stats()
    names = [f for f in getattr(stats, "_fields", None) or
             [x.name for x in __import__("dataclasses").fields(stats)]]
    assert names == ["live_keys", "tombstones", "total_records", "dead_records",
                     "segment_count", "bytes_on_disk"]


def test_stats_survives_reopen(kv, tmp_path):
    root = tmp_path / "db"
    with kv.KVStore(root) as store:
        store.set("a", "1")
        store.set("a", "2")
        before = store.stats()
    with kv.KVStore(root) as store:
        after = store.stats()
    assert (after.live_keys, after.total_records, after.dead_records) == (
        before.live_keys, before.total_records, before.dead_records)


# --------------------------------------------------------------------------- #
# 9. compaction
# --------------------------------------------------------------------------- #

def test_compact_returns_result_type(kv, tmp_path):
    with kv.KVStore(tmp_path / "db") as store:
        store.set("a", "1")
        assert isinstance(kv.compact(store), kv.CompactionResult)


def test_compact_result_fields(kv):
    assert kv.CompactionResult._fields == (
        "segments_removed", "records_written", "records_dropped", "bytes_reclaimed")


def test_compact_drops_tombstones(kv, tmp_path):
    with kv.KVStore(tmp_path / "db") as store:
        store.set("a", "1")
        store.set("b", "2")
        store.delete("b")
        kv.compact(store)
        assert store.stats().tombstones == 0


def test_compact_keeps_live_values(kv, tmp_path):
    with kv.KVStore(tmp_path / "db") as store:
        store.set("a", "1")
        store.set("b", "2")
        store.delete("b")
        kv.compact(store)
        assert store.get("a") == "1"


def test_compact_deleted_key_stays_gone(kv, tmp_path):
    with kv.KVStore(tmp_path / "db") as store:
        store.set("a", "1")
        store.delete("a")
        kv.compact(store)
        assert store.get("a") is None


def test_compact_records_written(kv, tmp_path):
    with kv.KVStore(tmp_path / "db") as store:
        store.set("a", "1")
        store.set("b", "2")
        store.set("a", "3")
        store.delete("b")
        result = kv.compact(store)
        assert result.records_written == 1


def test_compact_records_dropped(kv, tmp_path):
    with kv.KVStore(tmp_path / "db") as store:
        store.set("a", "1")
        store.set("a", "2")
        store.set("a", "3")
        result = kv.compact(store)
        assert result.records_dropped == 2


def test_compact_removes_old_segments(kv, tmp_path):
    root = tmp_path / "db"
    with kv.KVStore(root, max_segment_bytes=20) as store:
        for i in range(5):
            store.set(f"k{i}", "v")
        result = kv.compact(store)
        assert result.segments_removed >= 2
        assert store.stats().segment_count == 1


def test_compact_new_segment_id_is_max_plus_one(kv, tmp_path):
    root = tmp_path / "db"
    with kv.KVStore(root, max_segment_bytes=20) as store:
        for i in range(4):
            store.set(f"k{i}", "v")
        highest = max(int(p.name[:6]) for p in root.glob("*.seg"))
        kv.compact(store)
    assert [p.name for p in root.glob("*.seg")] == [f"{highest + 1:06d}.seg"]


def test_compact_preserves_keys_order(kv, tmp_path):
    with kv.KVStore(tmp_path / "db", max_segment_bytes=24) as store:
        for key in ("a", "b", "c", "d"):
            store.set(key, "v")
        store.set("b", "again")
        expected = store.keys()
        kv.compact(store)
        assert store.keys() == expected


def test_compact_order_survives_reopen(kv, tmp_path):
    root = tmp_path / "db"
    with kv.KVStore(root, max_segment_bytes=24) as store:
        for key in ("x", "y", "z"):
            store.set(key, "v")
        store.set("x", "again")
        kv.compact(store)
        expected = store.keys()
    with kv.KVStore(root) as store:
        assert store.keys() == expected


def test_compact_leaves_no_tmp_file(kv, tmp_path):
    root = tmp_path / "db"
    with kv.KVStore(root) as store:
        store.set("a", "1")
        kv.compact(store)
    assert list(root.glob("*.tmp")) == []


def test_compact_bytes_reclaimed_positive(kv, tmp_path):
    with kv.KVStore(tmp_path / "db") as store:
        for i in range(10):
            store.set("a", f"value{i}")
        result = kv.compact(store)
        assert result.bytes_reclaimed > 0


def test_compact_empty_store_is_safe(kv, tmp_path):
    with kv.KVStore(tmp_path / "db") as store:
        result = kv.compact(store)
        assert result.records_written == 0
        assert store.keys() == []


def test_compact_all_deleted_leaves_active_segment(kv, tmp_path):
    root = tmp_path / "db"
    with kv.KVStore(root) as store:
        store.set("a", "1")
        store.delete("a")
        kv.compact(store)
        assert store.stats().segment_count == 1
        store.set("b", "2")
        assert store.get("b") == "2"


def test_writes_after_compaction(kv, tmp_path):
    with kv.KVStore(tmp_path / "db") as store:
        store.set("a", "1")
        kv.compact(store)
        store.set("b", "2")
        assert store.keys() == ["a", "b"]


def test_compaction_result_is_reopen_consistent(kv, tmp_path):
    root = tmp_path / "db"
    with kv.KVStore(root) as store:
        store.set("a", "1")
        store.set("a", "2")
        store.set("b", "3")
        kv.compact(store)
        expected = {k: store.get(k) for k in store.keys()}
    with kv.KVStore(root) as store:
        assert {k: store.get(k) for k in store.keys()} == expected


def test_compact_twice_is_stable(kv, tmp_path):
    with kv.KVStore(tmp_path / "db") as store:
        store.set("a", "1")
        store.set("b", "2")
        kv.compact(store)
        first = store.keys()
        second = kv.compact(store)
        assert store.keys() == first
        assert second.records_dropped == 0


def test_compact_empty_value_preserved(kv, tmp_path):
    with kv.KVStore(tmp_path / "db") as store:
        store.set("a", "")
        kv.compact(store)
        assert store.get("a") == ""


def test_compact_total_records_after(kv, tmp_path):
    with kv.KVStore(tmp_path / "db") as store:
        store.set("a", "1")
        store.set("a", "2")
        store.set("b", "3")
        kv.compact(store)
        assert store.stats().total_records == 2


def test_compact_dead_records_zero_after(kv, tmp_path):
    with kv.KVStore(tmp_path / "db") as store:
        for i in range(5):
            store.set("a", f"v{i}")
        kv.compact(store)
        assert store.stats().dead_records == 0


# --------------------------------------------------------------------------- #
# 10. CLI
# --------------------------------------------------------------------------- #

def test_cli_set_exit_zero(tmp_path):
    assert cli(tmp_path / "db", "set", "a", "1").returncode == 0


def test_cli_get_prints_value(tmp_path):
    root = tmp_path / "db"
    cli(root, "set", "a", "hello")
    done = cli(root, "get", "a")
    assert done.returncode == 0
    assert done.stdout == "hello\n"


def test_cli_get_missing_exit_one(tmp_path):
    done = cli(tmp_path / "db", "get", "ghost")
    assert done.returncode == 1


def test_cli_get_missing_prints_nothing(tmp_path):
    assert cli(tmp_path / "db", "get", "ghost").stdout == ""


def test_cli_get_empty_value(tmp_path):
    root = tmp_path / "db"
    cli(root, "set", "a", "")
    done = cli(root, "get", "a")
    assert done.returncode == 0
    assert done.stdout == "\n"


def test_cli_delete_live_exit_zero(tmp_path):
    root = tmp_path / "db"
    cli(root, "set", "a", "1")
    assert cli(root, "delete", "a").returncode == 0


def test_cli_delete_absent_exit_one(tmp_path):
    assert cli(tmp_path / "db", "delete", "ghost").returncode == 1


def test_cli_list(tmp_path):
    root = tmp_path / "db"
    cli(root, "set", "b", "1")
    cli(root, "set", "a", "2")
    assert cli(root, "list").stdout == "b\na\n"


def test_cli_list_empty(tmp_path):
    assert cli(tmp_path / "db", "list").stdout == ""


def test_cli_stats_line(tmp_path):
    root = tmp_path / "db"
    cli(root, "set", "a", "1")
    out = cli(root, "stats").stdout.strip()
    fields = [pair.split("=")[0] for pair in out.split()]
    assert fields == ["live_keys", "tombstones", "total_records", "dead_records",
                      "segment_count", "bytes_on_disk"]


def test_cli_stats_values(tmp_path):
    root = tmp_path / "db"
    cli(root, "set", "a", "1")
    cli(root, "set", "a", "2")
    out = cli(root, "stats").stdout.strip()
    assert "live_keys=1" in out and "total_records=2" in out and "dead_records=1" in out


def test_cli_compact_line(tmp_path):
    root = tmp_path / "db"
    cli(root, "set", "a", "1")
    cli(root, "set", "a", "2")
    out = cli(root, "compact").stdout.strip()
    fields = [pair.split("=")[0] for pair in out.split()]
    assert fields == ["removed", "written", "dropped", "reclaimed"]


def test_cli_compact_exit_zero(tmp_path):
    root = tmp_path / "db"
    cli(root, "set", "a", "1")
    assert cli(root, "compact").returncode == 0


@pytest.mark.parametrize("args", [("frobnicate",), ("set",), ("set", "a"),
                                  ("get",), ("get", "a", "b"), ("delete",),
                                  ("list", "extra")])
def test_cli_usage_errors_exit_two(tmp_path, args):
    assert cli(tmp_path / "db", *args).returncode == 2


def test_cli_usage_error_writes_stderr(tmp_path):
    done = cli(tmp_path / "db", "frobnicate")
    assert done.stderr != ""


def test_cli_usage_error_silent_stdout(tmp_path):
    assert cli(tmp_path / "db", "frobnicate").stdout == ""


def test_cli_empty_key_exit_two(tmp_path):
    """An empty key is a ValueError from the store, which the CLI maps to exit 2."""
    done = cli(tmp_path / "db", "set", "", "1")
    assert done.returncode == 2
    assert done.stdout == ""


def test_cli_corrupt_segment_exit_three(kv, tmp_path):
    root = tmp_path / "db"
    cli(root, "set", "a", "1")
    seg = root / "000001.seg"
    data = bytearray(seg.read_bytes())
    data[-1] ^= 0xFF
    seg.write_bytes(bytes(data))
    done = cli(root, "get", "a")
    assert done.returncode == 3
    assert done.stdout == ""


def test_cli_max_segment_bytes_flag(tmp_path):
    root = tmp_path / "db"
    for i in range(4):
        assert cli(root, "--max-segment-bytes", "20", "set", f"k{i}", "v").returncode == 0
    out = cli(root, "stats").stdout
    assert "segment_count=1" not in out


def test_cli_bad_max_segment_bytes_exit_two(tmp_path):
    assert cli(tmp_path / "db", "--max-segment-bytes", "4", "set", "a", "1").returncode == 2


def test_cli_non_numeric_max_segment_bytes_exit_two(tmp_path):
    assert cli(tmp_path / "db", "--max-segment-bytes", "abc", "set", "a", "1").returncode == 2


def test_cli_persists_between_invocations(tmp_path):
    root = tmp_path / "db"
    cli(root, "set", "a", "1")
    cli(root, "set", "b", "2")
    assert cli(root, "list").stdout == "a\nb\n"


def test_cli_main_returns_int(kv):
    module = importlib.import_module("kvstore.__main__")
    assert callable(module.main)


# --------------------------------------------------------------------------- #
# 11. package surface and hygiene
# --------------------------------------------------------------------------- #

_EXPECTED_ALL = {
    "KVStore", "Stats", "Index", "Location", "Segment", "CompactionResult", "compact",
    "encode_record", "decode_record", "KVStoreError", "RecordError",
    "IncompleteRecordError", "CorruptRecordError", "CorruptSegmentError",
}


def test_all_exports(kv):
    assert set(kv.__all__) == _EXPECTED_ALL


def test_all_names_present(kv):
    missing = [name for name in _EXPECTED_ALL if not hasattr(kv, name)]
    assert missing == []


def test_exception_hierarchy(kv):
    assert issubclass(kv.RecordError, kv.KVStoreError)
    assert issubclass(kv.IncompleteRecordError, kv.RecordError)
    assert issubclass(kv.CorruptRecordError, kv.RecordError)
    assert issubclass(kv.CorruptSegmentError, kv.KVStoreError)


def test_incomplete_is_not_corrupt(kv):
    assert not issubclass(kv.IncompleteRecordError, kv.CorruptRecordError)


def test_no_forbidden_serialisation_modules():
    forbidden = {"pickle", "shelve", "dbm", "sqlite3", "marshal"}
    found = []
    for path in Path(".").rglob("*.py"):
        if any(part in _IGNORED_DIRS for part in path.parts):
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for name in forbidden:
            if f"import {name}" in text:
                found.append(f"{path}: {name}")
    assert found == []


def test_expected_modules_exist():
    for name in ("__init__", "errors", "record", "segment", "index", "store",
                 "compact", "__main__"):
        assert Path("kvstore") .joinpath(f"{name}.py").is_file(), name
