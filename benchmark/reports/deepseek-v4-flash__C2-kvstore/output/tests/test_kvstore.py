"""Tests for the kvstore package."""

import os
import pathlib
import struct
import zlib
import sys
import pytest

from kvstore import (
    KVStore, Stats, Index, Location, Segment,
    compact, CompactionResult,
    encode_record, decode_record,
    KVStoreError, RecordError, IncompleteRecordError,
    CorruptRecordError, CorruptSegmentError,
)


class TestRecordCodec:
    def test_round_trip_simple(self) -> None:
        blob = encode_record('hello', 'world')
        key, value, size = decode_record(blob)
        assert key == "hello"
        assert value == "world"
        assert size == len(blob)

    def test_round_trip_unicode(self) -> None:
        blob = encode_record('kljuch', 'znachenie')
        key, value, size = decode_record(blob)
        assert key == "kljuch"
        assert value == "znachenie"
        assert size == len(blob)

    def test_empty_value(self) -> None:
        blob = encode_record('k', '')
        key, value, size = decode_record(blob)
        assert key == "k"
        assert value == ""
        assert size == len(blob)
        tomb = encode_record('k', None)
        assert len(blob) == 16
        assert len(tomb) == 16
        assert blob[4] == 0x00
        assert tomb[4] == 0x01
        k2, v2, _ = decode_record(tomb)
        assert k2 == "k"
        assert v2 is None

    def test_tombstone_encoding(self) -> None:
        blob = encode_record('delkey', None)
        key, value, size = decode_record(blob)
        assert key == "delkey"
        assert value is None
        assert size == 21

    def test_decode_at_offset(self) -> None:
        blob = encode_record("a", "1") + encode_record("b", "2")
        k1, v1, s1 = decode_record(blob, 0)
        assert k1 == "a" and v1 == "1"
        k2, v2, s2 = decode_record(blob, s1)
        assert k2 == "b" and v2 == "2"
        assert s1 + s2 == len(blob)

    def test_incomplete_header(self) -> None:
        with pytest.raises(IncompleteRecordError):
            decode_record(b'KVR1', 0)

    def test_incomplete_body(self) -> None:
        blob = encode_record('hello', 'world')
        with pytest.raises(IncompleteRecordError):
            decode_record(blob[:20], 0)

    def test_bad_magic(self) -> None:
        blob = encode_record("k", "v")
        bad = b'XXXX' + blob[4:]
        with pytest.raises(CorruptRecordError, match='bad magic'):
            decode_record(bad)

    def test_unknown_flags(self) -> None:
        blob = bytearray(encode_record("k", "v"))
        blob[4] = 0xFF
        with pytest.raises(CorruptRecordError, match='unknown flags'):
            decode_record(bytes(blob))

    def test_key_len_zero(self) -> None:
        blob = bytearray(encode_record("k", "v"))
        blob[5:7] = (0).to_bytes(2, 'big')
        with pytest.raises(CorruptRecordError, match='key_len is 0'):
            decode_record(bytes(blob))

    def test_tombstone_with_nonzero_value_len(self) -> None:
        blob = encode_record("k", None)
        bad = bytearray(blob)
        bad[7:11] = (5).to_bytes(4, 'big')
        bad.extend(b'\x00' * 5)
        payload = bad[15:16] + b'\x00' * 5
        bad[11:15] = zlib.crc32(payload).to_bytes(4, 'big')
        with pytest.raises(CorruptRecordError, match='tombstone'):
            decode_record(bytes(bad))

    def test_crc_mismatch(self) -> None:
        blob = bytearray(encode_record("k", "v"))
        blob[14] ^= 0xFF
        with pytest.raises(CorruptRecordError, match='CRC mismatch'):
            decode_record(bytes(blob))

    def test_non_utf8_key(self) -> None:
        magic = b'KVR1'
        flags = 0x00
        key_len = 2
        value_len = 1
        key_bytes = b'\xff\xfe'
        value_bytes = b'a'
        payload = key_bytes + value_bytes
        crc = zlib.crc32(payload)
        header = struct.pack('!4s B H I I', magic, flags, key_len, value_len, crc)
        blob = header + payload
        with pytest.raises(CorruptRecordError) as exc:
            decode_record(blob)
        assert 'UTF-8' in str(exc.value)

    def test_non_utf8_value(self) -> None:
        magic = b'KVR1'
        flags = 0x00
        key_len = 1
        value_len = 2
        key_bytes = b'a'
        value_bytes = b'\xff\xfe'
        payload = key_bytes + value_bytes
        crc = zlib.crc32(payload)
        header = struct.pack('!4s B H I I', magic, flags, key_len, value_len, crc)
        blob = header + payload
        with pytest.raises(CorruptRecordError) as exc:
            decode_record(blob)
        assert 'UTF-8' in str(exc.value)


class TestIndex:
    def test_put_get(self) -> None:
        idx = Index()
        loc = Location(1, 0)
        idx.put("a", loc, tombstone=False)
        assert idx.get("a") == loc
        assert idx.get("b") is None

    def test_tombstone_get_none(self) -> None:
        idx = Index()
        idx.put('a', Location(1, 0), tombstone=True)
        assert idx.get('a') is None

    def test_live_keys_order(self) -> None:
        idx = Index()
        idx.put('b', Location(1, 100), tombstone=False)
        idx.put('a', Location(1, 0), tombstone=False)
        assert idx.live_keys() == ['a', 'b']

    def test_put_replaces(self) -> None:
        idx = Index()
        idx.put('a', Location(1, 0), tombstone=False)
        idx.put('a', Location(1, 100), tombstone=False)
        assert idx.live_keys() == ['a']
        assert idx.get('a') == Location(1, 100)

    def test_tombstone_count(self) -> None:
        idx = Index()
        idx.put('a', Location(1, 0), tombstone=False)
        idx.put('b', Location(1, 1), tombstone=True)
        idx.put('c', Location(1, 2), tombstone=False)
        assert idx.tombstone_count() == 1

    def test_len(self) -> None:
        idx = Index()
        assert len(idx) == 0
        idx.put('a', Location(1, 0), tombstone=False)
        idx.put('b', Location(1, 5), tombstone=True)
        assert len(idx) == 1


class TestKVStoreBasic:
    def test_set_and_get(self, tmp_path: pathlib.Path) -> None:
        root = tmp_path / 'data'
        store = KVStore(str(root))
        store.set("a", "1")
        assert store.get("a") == "1"
        store.close()

    def test_get_missing(self, tmp_path: pathlib.Path) -> None:
        store = KVStore(str(tmp_path / 'data'))
        assert store.get('nonexistent') is None
        store.close()

    def test_get_empty_value(self, tmp_path: pathlib.Path) -> None:
        store = KVStore(str(tmp_path / 'data'))
        store.set("k", "")
        assert store.get("k") == ""
        store.close()

    def test_delete_live(self, tmp_path: pathlib.Path) -> None:
        store = KVStore(str(tmp_path / 'data'))
        store.set("a", "1")
        assert store.delete('a') is True
        assert store.get('a') is None
        store.close()

    def test_delete_absent(self, tmp_path: pathlib.Path) -> None:
        store = KVStore(str(tmp_path / 'data'))
        assert store.delete('nonexistent') is False
        store.close()

    def test_delete_already_tombstoned(self, tmp_path: pathlib.Path) -> None:
        store = KVStore(str(tmp_path / 'data'))
        store.set("a", "1")
        store.delete('a')
        assert store.delete('a') is False
        store.close()

    def test_keys_empty(self, tmp_path: pathlib.Path) -> None:
        store = KVStore(str(tmp_path / 'data'))
        assert store.keys() == []
        store.close()

    def test_keys_ordering(self, tmp_path: pathlib.Path) -> None:
        store = KVStore(str(tmp_path / 'data'))
        store.set("b", "2")
        store.set("a", "1")
        assert store.keys() == ['b', 'a']
        store.set("b", "updated")
        assert store.keys() == ['a', 'b']
        store.close()

    def test_persistence(self, tmp_path: pathlib.Path) -> None:
        root = str(tmp_path / 'data')
        store = KVStore(root)
        store.set("a", "1")
        store.set("b", "2")
        store.close()
        store2 = KVStore(root)
        assert store2.get("a") == "1"
        assert store2.get("b") == "2"
        assert store2.keys() == ['a', 'b']
        store2.close()

    def test_tombstone_persistence(self, tmp_path: pathlib.Path) -> None:
        root = str(tmp_path / 'data')
        store = KVStore(root)
        store.set("a", "1")
        store.delete('a')
        store.close()
        store2 = KVStore(root)
        assert store2.get('a') is None
        store2.close()


class TestRollover:
    def test_rollover_creates_new_segment(self, tmp_path) -> None:
        store = KVStore(str(tmp_path / 'data'), max_segment_bytes=32)
        store.set("ab", "x")
        assert store.stats().segment_count == 1
        store.set("cd", "y")
        assert store.stats().segment_count == 2
        store.close()

    def test_large_record_fits_in_empty_segment(self, tmp_path) -> None:
        store = KVStore(str(tmp_path / 'data'), max_segment_bytes=16)
        store.set("k", "x" * 1000)
        assert store.get("k") == "x" * 1000
        store.close()


class TestStats:
    def test_stats_fields(self, tmp_path) -> None:
        store = KVStore(str(tmp_path / 'data'))
        stats = store.stats()
        assert isinstance(stats, Stats)
        assert stats.live_keys == 0
        assert stats.tombstones == 0
        assert stats.total_records == 0
        assert stats.dead_records == 0
        assert stats.segment_count == 1
        assert stats.bytes_on_disk == 0
        store.close()

    def test_stats_with_data(self, tmp_path) -> None:
        store = KVStore(str(tmp_path / 'data'))
        store.set("a", "1")
        store.set("a", "2")
        store.set("b", "3")
        store.delete('b')
        stats = store.stats()
        assert stats.live_keys == 1
        assert stats.tombstones == 1
        assert stats.total_records == 4
        assert stats.dead_records == 2
        store.close()


class TestCompaction:
    def test_compact_basic(self, tmp_path) -> None:
        store = KVStore(str(tmp_path / 'data'))
        store.set("a", "1")
        store.set("b", "2")
        result = compact(store)
        assert result.segments_removed >= 1
        assert result.records_written == 2
        assert store.get("a") == "1"
        assert store.get("b") == "2"
        store.close()

    def test_compact_drops_tombstones(self, tmp_path) -> None:
        store = KVStore(str(tmp_path / 'data'))
        store.set("a", "1")
        store.set("b", "2")
        store.delete('b')
        result = compact(store)
        assert result.records_written == 1
        assert store.get("a") == "1"
        assert store.get('b') is None
        store.close()

    def test_compact_empty_store(self, tmp_path) -> None:
        store = KVStore(str(tmp_path / 'data'))
        result = compact(store)
        assert result.records_written == 0
        assert store.stats().segment_count >= 1
        store.close()


class TestValidation:
    def test_non_str_key_raises_typeerror(self, tmp_path) -> None:
        store = KVStore(str(tmp_path / 'data'))
        with pytest.raises(TypeError):
            store.set(123, 'value')
        store.close()

    def test_key_bytes_raises_typeerror(self, tmp_path) -> None:
        store = KVStore(str(tmp_path / 'data'))
        with pytest.raises(TypeError):
            store.set(b'k', 'v')
        store.close()

    def test_non_str_value_raises_typeerror(self, tmp_path) -> None:
        store = KVStore(str(tmp_path / 'data'))
        with pytest.raises(TypeError):
            store.set('k', 42)
        store.close()

    def test_overlong_key_raises_valueerror(self, tmp_path) -> None:
        store = KVStore(str(tmp_path / 'data'))
        with pytest.raises(ValueError):
            store.set('x' * 70000, 'v')
        store.close()

    def test_max_segment_bytes_below_16(self, tmp_path) -> None:
        with pytest.raises(ValueError):
            KVStore(str(tmp_path / 'data'), max_segment_bytes=15)

    def test_max_segment_bytes_not_int(self, tmp_path) -> None:
        with pytest.raises(ValueError):
            KVStore(str(tmp_path / 'data'), max_segment_bytes='4096')


class TestClosedStore:
    def test_operations_on_closed_store_raise(self, tmp_path) -> None:
        store = KVStore(str(tmp_path / 'data'))
        store.close()
        with pytest.raises(ValueError):
            store.get('a')
        with pytest.raises(ValueError):
            store.set('a', '1')
        with pytest.raises(ValueError):
            store.delete('a')
        with pytest.raises(ValueError):
            store.keys()
        with pytest.raises(ValueError):
            store.stats()

    def test_close_idempotent(self, tmp_path) -> None:
        store = KVStore(str(tmp_path / 'data'))
        store.close()
        store.close()


class TestCorruptSegmentError:
    def test_path_and_offset_in_str(self, tmp_path) -> None:
        err = CorruptSegmentError(tmp_path / '000001.seg', 42, 'bad magic')
        assert '000001.seg' in str(err)
        assert '42' in str(err)

    def test_truncated_tail_recovery(self, tmp_path) -> None:
        root = tmp_path / 'data'
        root.mkdir()
        blob = encode_record('a', '1')
        (root / '000001.seg').write_bytes(blob + b'KVR')
        store = KVStore(str(root))
        assert store.get('a') == '1'
        store.close()


class TestCLI:
    def _run(self, tmp_path, *args):
        import subprocess
        root = str(tmp_path / 'data')
        cmd = [sys.executable, '-m', 'kvstore', root] + list(args)
        r = subprocess.run(cmd, capture_output=True, text=True)
        return r.returncode, r.stdout, r.stderr

    def test_cli_set_get(self, tmp_path) -> None:
        rc, out, err = self._run(tmp_path, "set", "a", "1")
        assert rc == 0
        rc, out, err = self._run(tmp_path, "get", "a")
        assert rc == 0
        assert out.strip() == "1"

    def test_cli_get_missing_exit_1(self, tmp_path) -> None:
        rc, out, err = self._run(tmp_path, "get", "zz")
        assert rc == 1
        assert out == ""

    def test_cli_delete_live_exit_0(self, tmp_path) -> None:
        self._run(tmp_path, "set", "a", "1")
        rc, out, err = self._run(tmp_path, "delete", "a")
        assert rc == 0

    def test_cli_delete_absent_exit_1(self, tmp_path) -> None:
        rc, out, err = self._run(tmp_path, "delete", "zz")
        assert rc == 1

    def test_cli_list(self, tmp_path) -> None:
        self._run(tmp_path, "set", "b", "2")
        self._run(tmp_path, "set", "a", "1")
        rc, out, err = self._run(tmp_path, "list")
        assert rc == 0
        assert out.splitlines() == ['b', 'a']

    def test_cli_stats(self, tmp_path) -> None:
        self._run(tmp_path, "set", "a", "1")
        rc, out, err = self._run(tmp_path, "stats")
        assert rc == 0
        assert 'live_keys=' in out
        assert 'bytes_on_disk=' in out

    def test_cli_compact(self, tmp_path) -> None:
        self._run(tmp_path, "set", "a", "1")
        rc, out, err = self._run(tmp_path, "compact")
        assert rc == 0
        assert 'removed=' in out

    def test_cli_unknown_command_exit_2(self, tmp_path) -> None:
        rc, out, err = self._run(tmp_path, "unknown")
        assert rc == 2

    def test_cli_bad_max_segment_bytes_exit_2(self, tmp_path) -> None:
        rc, out, err = self._run(tmp_path, "--max-segment-bytes", "-1", "get", "k")
        assert rc == 2
