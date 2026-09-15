"""In-memory index mapping each key to its newest record location."""

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
        """Record the newest record for ``key``, replacing any earlier one."""
        self._entries[key] = (loc, tombstone)

    def get(self, key: str) -> Location | None:
        """Location of the newest record, or None if absent or tombstoned."""
        entry = self._entries.get(key)
        if entry is None or entry[1]:
            return None
        return entry[0]

    def live_keys(self) -> list[str]:
        """Live keys ordered by newest-record position (seg_id, offset)."""
        live = [
            (loc.seg_id, loc.offset, key)
            for key, (loc, tombstone) in self._entries.items()
            if not tombstone
        ]
        live.sort()
        return [key for _seg_id, _offset, key in live]

    def tombstone_count(self) -> int:
        return sum(1 for _loc, tombstone in self._entries.values() if tombstone)

    def __len__(self) -> int:
        return sum(1 for _loc, tombstone in self._entries.values() if not tombstone)
