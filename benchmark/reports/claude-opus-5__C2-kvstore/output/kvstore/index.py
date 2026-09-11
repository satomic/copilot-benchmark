"""In-memory index mapping a key to the location of its newest record."""

from __future__ import annotations

import dataclasses

__all__ = ["Location", "Index"]


@dataclasses.dataclass(frozen=True)
class Location:
    """Where a record lives: which segment, and at which byte offset."""

    seg_id: int
    offset: int


class Index:
    """Key -> newest known record location, plus its tombstone flag."""

    def __init__(self) -> None:
        self._entries: dict[str, tuple[Location, bool]] = {}

    def put(self, key: str, loc: Location, *, tombstone: bool) -> None:
        """Record the newest known record for ``key``, replacing any earlier one."""
        self._entries[key] = (loc, tombstone)

    def get(self, key: str) -> Location | None:
        """Return the location of a live key, or ``None`` if absent/tombstoned."""
        entry = self._entries.get(key)
        if entry is None or entry[1]:
            return None
        return entry[0]

    def is_tombstoned(self, key: str) -> bool:
        """True when the key's newest record is a tombstone."""
        entry = self._entries.get(key)
        return entry is not None and entry[1]

    def live_keys(self) -> list[str]:
        """Live keys ordered by their newest record's ``(seg_id, offset)``."""
        live = [
            (loc.seg_id, loc.offset, key)
            for key, (loc, tombstone) in self._entries.items()
            if not tombstone
        ]
        live.sort()
        return [key for _seg_id, _offset, key in live]

    def tombstone_count(self) -> int:
        """Number of distinct keys whose newest record is a tombstone."""
        return sum(1 for _loc, tombstone in self._entries.values() if tombstone)

    def __len__(self) -> int:
        """Number of live keys."""
        return sum(1 for _loc, tombstone in self._entries.values() if not tombstone)
