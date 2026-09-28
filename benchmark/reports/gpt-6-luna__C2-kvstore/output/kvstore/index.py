"""In-memory mapping from keys to their newest record locations."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Location:
    """Location of a record within a segment."""

    seg_id: int
    offset: int


class Index:
    """Track the newest location and tombstone state for each key."""

    def __init__(self) -> None:
        self._entries: dict[str, tuple[Location, bool]] = {}

    def put(self, key: str, loc: Location, *, tombstone: bool) -> None:
        """Replace the newest known entry for ``key``."""
        self._entries[key] = (loc, tombstone)

    def get(self, key: str) -> Location | None:
        """Return a live key's location, or ``None`` if absent or deleted."""
        entry = self._entries.get(key)
        return None if entry is None or entry[1] else entry[0]

    def live_keys(self) -> list[str]:
        """Return live keys ordered by their newest record position."""
        return [
            key
            for key, (loc, tombstone) in sorted(
                self._entries.items(), key=lambda item: (item[1][0].seg_id, item[1][0].offset)
            )
            if not tombstone
        ]

    def tombstone_count(self) -> int:
        """Return the number of distinct keys currently deleted."""
        return sum(tombstone for _, tombstone in self._entries.values())

    def __len__(self) -> int:
        """Return the number of live keys."""
        return sum(not tombstone for _, tombstone in self._entries.values())
