from dataclasses import dataclass


@dataclass(frozen=True)
class Location:
    seg_id: int
    offset: int


class Index:
    def __init__(self) -> None:
        self._items: dict[str, tuple[Location, bool]] = {}

    def put(self, key: str, loc: Location, *, tombstone: bool) -> None:
        self._items[key] = (loc, tombstone)

    def get(self, key: str) -> Location | None:
        item = self._items.get(key)
        return None if item is None or item[1] else item[0]

    def live_keys(self) -> list[str]:
        items = ((loc, key) for key, (loc, dead) in self._items.items() if not dead)
        return [key for _, key in sorted(items, key=lambda pair: (pair[0].seg_id, pair[0].offset))]

    def tombstone_count(self) -> int:
        return sum(1 for _, dead in self._items.values() if dead)

    def __len__(self) -> int:
        return sum(1 for _, dead in self._items.values() if not dead)
