from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Location:
    seg_id: int
    offset: int


class Index:
    def __init__(self) -> None:
        self._entries: dict[str, tuple[Location, bool]] = {}

    def put(self, key: str, loc: Location, *, tombstone: bool) -> None:
        self._entries[key] = (loc, tombstone)

    def get(self, key: str) -> Location | None:
        item = self._entries.get(key)
        if item is None or item[1]:
            return None
        return item[0]

    def live_keys(self) -> list[str]:
        live = []
        for key, (loc, tombstone) in self._entries.items():
            if not tombstone:
                live.append((loc, key))
        live.sort(key=lambda item: (item[0].seg_id, item[0].offset))
        return [key for _, key in live]

    def tombstone_count(self) -> int:
        return sum(1 for _, tombstone in self._entries.values() if tombstone)

    def __len__(self) -> int:
        return sum(1 for _, tombstone in self._entries.values() if not tombstone)
