"""In-memory index mapping keys to their newest on-disk location."""

from __future__ import annotations

import dataclasses


@dataclasses.dataclass(frozen=True)
class Location:
    seg_id: int
    offset: int


@dataclasses.dataclass
class _Entry:
    loc: Location
    tombstone: bool


class Index:
    """Maps key -> newest Location, tracking liveness order."""

    def __init__(self) -> None:
        self._entries: dict[str, _Entry] = {}

    def put(self, key: str, loc: Location, *, tombstone: bool) -> None:
        self._entries[key] = _Entry(loc=loc, tombstone=tombstone)

    def get(self, key: str) -> Location | None:
        entry = self._entries.get(key)
        if entry is None or entry.tombstone:
            return None
        return entry.loc

    def live_keys(self) -> list[str]:
        live = [(k, e) for k, e in self._entries.items() if not e.tombstone]
        live.sort(key=lambda kv: (kv[1].loc.seg_id, kv[1].loc.offset))
        return [k for k, _ in live]

    def tombstone_count(self) -> int:
        return sum(1 for e in self._entries.values() if e.tombstone)

    def __len__(self) -> int:
        return sum(1 for e in self._entries.values() if not e.tombstone)
