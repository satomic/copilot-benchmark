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

    def is_live(self, key: str) -> bool:
        return self.get(key) is not None

    def live_keys(self) -> list[str]:
        live = [(loc, key) for key, (loc, dead) in self._entries.items() if not dead]
        live.sort(key=lambda item: (item[0].seg_id, item[0].offset))
        return [key for _, key in live]

    def tombstone_count(self) -> int:
        return sum(1 for _, dead in self._entries.values() if dead)

    def __len__(self) -> int:
        return len(self._entries) - self.tombstone_count()
