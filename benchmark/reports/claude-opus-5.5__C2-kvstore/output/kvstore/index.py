"""In-memory index mapping each key to the location of its newest record."""

from __future__ import annotations

import dataclasses


@dataclasses.dataclass(frozen=True)
class Location:
    seg_id: int
    offset: int


class Index:
    def __init__(self) -> None:
        self._entries: dict[str, tuple[Location, bool]] = {}
        self._tombstones = 0

    def put(self, key: str, loc: Location, *, tombstone: bool) -> None:
        old = self._entries.get(key)
        if old is not None and old[1]:
            self._tombstones -= 1
        if tombstone:
            self._tombstones += 1
        self._entries[key] = (loc, tombstone)

    def get(self, key: str) -> Location | None:
        entry = self._entries.get(key)
        if entry is None or entry[1]:
            return None
        return entry[0]

    def live_keys(self) -> list[str]:
        live = [(loc.seg_id, loc.offset, key) for key, (loc, dead) in self._entries.items() if not dead]
        live.sort()
        return [key for _, _, key in live]

    def tombstone_count(self) -> int:
        return self._tombstones

    def __len__(self) -> int:
        return len(self._entries) - self._tombstones
