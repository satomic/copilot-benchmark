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
        if entry is None:
            return None
        loc, is_tombstone = entry
        return None if is_tombstone else loc

    def live_keys(self) -> list[str]:
        live = [
            (loc.seg_id, loc.offset, key)
            for key, (loc, is_tombstone) in self._entries.items()
            if not is_tombstone
        ]
        live.sort()
        return [key for _, _, key in live]

    def tombstone_count(self) -> int:
        return sum(1 for _, is_tombstone in self._entries.values() if is_tombstone)

    def __len__(self) -> int:
        return sum(1 for _, is_tombstone in self._entries.values() if not is_tombstone)
