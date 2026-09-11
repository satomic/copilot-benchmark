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
        entry = self._entries.get(key)
        return None if entry is None or entry[1] else entry[0]

    def live_keys(self) -> list[str]:
        live = [(key, loc) for key, (loc, dead) in self._entries.items() if not dead]
        live.sort(key=lambda entry: (entry[1].seg_id, entry[1].offset))
        return [key for key, _ in live]

    def tombstone_count(self) -> int:
        return sum(tombstone for _, tombstone in self._entries.values())

    def __len__(self) -> int:
        return len(self._entries) - self.tombstone_count()
