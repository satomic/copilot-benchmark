"""In-memory index: key -> newest record location."""
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
        self._entries[key] = (loc, tombstone)

    def get(self, key: str) -> Location | None:
        entry = self._entries.get(key)
        if entry is None or entry[1]:
            return None
        return entry[0]

    def live_keys(self) -> list[str]:
        live = [(loc.seg_id, loc.offset, k)
                for k, (loc, tomb) in self._entries.items() if not tomb]
        live.sort()
        return [k for _, _, k in live]

    def tombstone_count(self) -> int:
        return sum(1 for _, tomb in self._entries.values() if tomb)

    def __len__(self) -> int:
        return sum(1 for _, tomb in self._entries.values() if not tomb)
