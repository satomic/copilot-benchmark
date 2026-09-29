import dataclasses
from typing import Optional


@dataclasses.dataclass(frozen=True)
class Location:
    seg_id: int
    offset: int


class Index:
    """In-memory index mapping keys to their newest record location."""

    def __init__(self) -> None:
        self._entries: dict[str, tuple[Location, bool]] = {}
        # _entries[key] = (location, is_tombstone)

    def put(self, key: str, loc: Location, *, tombstone: bool) -> None:
        self._entries[key] = (loc, tombstone)

    def get(self, key: str) -> Location | None:
        entry = self._entries.get(key)
        if entry is None:
            return None
        loc, is_tombstone = entry
        if is_tombstone:
            return None
        return loc

    def live_keys(self) -> list[str]:
        """Return non-tombstoned keys ordered by (seg_id, offset) of their newest record."""
        result = [
            key
            for key, (loc, is_tombstone) in self._entries.items()
            if not is_tombstone
        ]
        result.sort(key=lambda k: (self._entries[k][0].seg_id, self._entries[k][0].offset))
        return result

    def tombstone_count(self) -> int:
        return sum(1 for _, (_, is_tomb) in self._entries.items() if is_tomb)

    def __len__(self) -> int:
        return sum(1 for _, (_, is_tomb) in self._entries.items() if not is_tomb)