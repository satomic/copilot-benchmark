"""In-memory key to record-location index."""

from __future__ import annotations

import dataclasses


@dataclasses.dataclass(frozen=True)
class Location:
    seg_id: int
    offset: int


class Index:
    def __init__(self) -> None:
        self._entries: dict[str, tuple[Location, bool]] = {}

    def put(self, key: str, loc: Location, *, tombstone: bool) -> None:
        """Record the newest location for key, replacing any earlier one."""
        self._entries[key] = (loc, tombstone)

    def get(self, key: str) -> Location | None:
        """Return the location of a live key, or None if absent or tombstoned."""
        found = self._entries.get(key)
        if found is None or found[1]:
            return None
        return found[0]

    def live_keys(self) -> list[str]:
        """Live keys ordered by newest-record position (seg_id, offset)."""
        ranked = [
            (loc.seg_id, loc.offset, key)
            for key, (loc, tombstone) in self._entries.items()
            if not tombstone
        ]
        ranked.sort()
        return [key for _, _, key in ranked]

    def tombstone_count(self) -> int:
        """Number of keys whose newest record is a tombstone."""
        return sum(1 for _, tombstone in self._entries.values() if tombstone)

    def __len__(self) -> int:
        """Number of live keys."""
        return sum(1 for _, tombstone in self._entries.values() if not tombstone)
