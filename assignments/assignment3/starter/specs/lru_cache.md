# `lru_cache` — Specification

An LRU (least-recently-used) cache with optional per-entry TTL.

## Public API

```python
from lru_cache import LRUCache

class LRUCache:
    def __init__(self, capacity: int) -> None: ...
    def put(self, key, value, ttl: float | None = None) -> None: ...
    def get(self, key): ...
    def __len__(self) -> int: ...
```

## Behavior

**C1. Capacity.** `capacity` is a positive integer. `__init__(0)` or `__init__(-5)` raises `ValueError`. Any non-int type for `capacity` is outside the spec.

**C2. `put(key, value, ttl)`.** Inserts or replaces the entry for `key`. If `ttl` is `None`, the entry never expires. If `ttl` is a number (int or float), the entry expires at `time.monotonic() + ttl`.

**C3. TTL replacement on re-put.** When `put` is called on a key that already exists, the old entry is completely replaced: its value, its TTL, and its expiration time are all superseded by the new arguments. Passing `ttl=None` to a re-put on a previously-TTL'd key clears the expiration.

**C4. Capacity eviction.** Inserting a new key (one not already in the cache) when `len(cache) == capacity` evicts the least-recently-used entry BEFORE the new entry is inserted. After the insert, `len(cache) == capacity`.

**C5. Use tracking.** Both `get(key)` and `put(key, ...)` on an existing key count as "uses" that reset that key's LRU position to most-recently-used. Inserting a new key does not affect the order of other keys.

**C6. Expiration on `get`.** `get(key)` on an expired entry raises `KeyError` and removes the entry from the cache. `get(key)` on a non-existent key also raises `KeyError`.

**C7. Length.** `len(cache)` returns the number of non-expired entries currently stored. Entries whose TTL has passed are not counted, even if they have not yet been accessed since expiring.

## Notes

- Time source is `time.monotonic()`. Tests that exercise TTL behavior will use real time (`time.sleep`) with millisecond-scale waits.
- The cache is not thread-safe; concurrent access is outside the spec.
- Values and keys can be any hashable Python object. The cache does not restrict their type.
