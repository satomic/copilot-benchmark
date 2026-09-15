"""In-memory map from key to the newest on-disk location."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Location:
    seg_id: int
    offset: int


class Index:
    def __init__(self) -> None:
        self._live: dict[str, Location] = {}
        self._tombstones: dict[str, Location] = {}

    def put(self, key: str, loc: Location, *, tombstone: bool) -> None:
        if tombstone:
            self._live.pop(key, None)
            self._tombstones[key] = loc
        else:
            self._tombstones.pop(key, None)
            self._live[key] = loc

    def get(self, key: str) -> Location | None:
        return self._live.get(key)

    def live_keys(self) -> list[str]:
        return sorted(
            self._live,
            key=lambda k: (self._live[k].seg_id, self._live[k].offset),
        )

    def tombstone_count(self) -> int:
        return len(self._tombstones)

    def __len__(self) -> int:
        return len(self._live)
