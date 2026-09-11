import dataclasses


@dataclasses.dataclass(frozen=True)
class Location:
    seg_id: int
    offset: int


class Index:
    def __init__(self) -> None:
        self._index: dict[str, tuple[Location, bool]] = {}
        self._order: list[str] = []
    
    def put(self, key: str, loc: Location, *, tombstone: bool) -> None:
        if key not in self._index:
            self._order.append(key)
        else:
            self._order.remove(key)
            self._order.append(key)
        
        self._index[key] = (loc, tombstone)
    
    def get(self, key: str) -> Location | None:
        if key not in self._index:
            return None
        
        loc, tombstone = self._index[key]
        if tombstone:
            return None
        return loc
    
    def live_keys(self) -> list[str]:
        return [
            key for key in self._order
            if key in self._index and not self._index[key][1]
        ]
    
    def tombstone_count(self) -> int:
        return sum(
            1 for key in self._index
            if self._index[key][1]
        )
    
    def __len__(self) -> int:
        return len(self.live_keys())
