"""In-memory index: key -> newest known record location."""

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
        """Record ``loc`` as the newest record for ``key``, replacing any earlier one."""
        self._entries[key] = (loc, tombstone)

    def get(self, key: str) -> Location | None:
        entry = self._entries.get(key)
        if entry is None or entry[1]:
            return None
        return entry[0]

    def live_keys(self) -> list[str]:
        """Live keys ordered by the position of their newest record."""
        live = [(loc, key) for key, (loc, tomb) in self._entries.items() if not tomb]
        live.sort(key=lambda item: (item[0].seg_id, item[0].offset))
        return [key for _, key in live]

    def tombstone_count(self) -> int:
        return sum(1 for _, tomb in self._entries.values() if tomb)

    def __len__(self) -> int:
        return sum(1 for _, tomb in self._entries.values() if not tomb)
