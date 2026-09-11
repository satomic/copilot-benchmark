"""The in-memory map from key to the location of its newest record."""

from __future__ import annotations

import dataclasses

__all__ = ["Location", "Index"]


@dataclasses.dataclass(frozen=True, order=True)
class Location:
    """Where a record lives: which segment, and at what byte offset."""

    seg_id: int
    offset: int


@dataclasses.dataclass(frozen=True)
class _Entry:
    loc: Location
    tombstone: bool


class Index:
    """Key to newest-record location.

    A plain ``dict`` is enough for ordering: ``put`` deletes before reinserting, so
    dict insertion order is exactly "ordered by the position of the newest record"
    for the append-only case, and recovery feeds records in ascending position order
    anyway. ``live_keys`` sorts explicitly rather than relying on that, so the
    contract holds even if records arrive out of order.
    """

    def __init__(self) -> None:
        self._entries: dict[str, _Entry] = {}

    def put(self, key: str, loc: Location, *, tombstone: bool) -> None:
        self._entries[key] = _Entry(loc, tombstone)

    def get(self, key: str) -> Location | None:
        entry = self._entries.get(key)
        if entry is None or entry.tombstone:
            return None
        return entry.loc

    def live_keys(self) -> list[str]:
        live = [(e.loc, k) for k, e in self._entries.items() if not e.tombstone]
        live.sort()
        return [key for _, key in live]

    def tombstone_count(self) -> int:
        return sum(1 for e in self._entries.values() if e.tombstone)

    def __len__(self) -> int:
        return sum(1 for e in self._entries.values() if not e.tombstone)

    def __contains__(self, key: object) -> bool:
        entry = self._entries.get(key) if isinstance(key, str) else None
        return entry is not None and not entry.tombstone
