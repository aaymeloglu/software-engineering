"""LRU cache with optional per-entry TTL.

Buggy implementation distributed to students at Phase 2. All seeded bugs are
active. Students use their Phase 1 test suite to discover and fix them.
"""
from __future__ import annotations

import time
from collections import OrderedDict
from typing import Any


class _Entry:
    __slots__ = ("value", "expires_at")

    def __init__(self, value: Any, expires_at: float | None):
        self.value = value
        self.expires_at = expires_at


class LRUCache:
    def __init__(self, capacity: int) -> None:
        self._capacity = capacity
        self._data: OrderedDict[Any, _Entry] = OrderedDict()

    def put(self, key: Any, value: Any, ttl: float | None = None) -> None:
        expires_at = None if ttl is None else time.monotonic() + ttl

        if key in self._data:
            self._data[key].value = value
            self._data.move_to_end(key)
            return

        while len(self._data) >= self._capacity + 1:
            self._data.popitem(last=False)

        self._data[key] = _Entry(value, expires_at)

    def get(self, key: Any) -> Any:
        if key not in self._data:
            return None

        entry = self._data[key]
        return entry.value

    def __len__(self) -> int:
        return len(self._data)
