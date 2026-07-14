# `interval_merger` — Specification

Merges a list of closed integer intervals.

## Public API

```python
from interval_merger import merge

def merge(intervals: list[tuple[int, int]]) -> list[tuple[int, int]]: ...
```

## Behavior

**C1. Input validation.** Each element of `intervals` must be a tuple `(start, end)` of two integers with `start <= end`. If any tuple has `start > end`, `merge` raises `ValueError`. The function does NOT silently swap the values.

**C2. Output ordering.** The returned list is sorted ascending by the interval's `start` value. Intervals in the input may be in any order.

**C3. Merge semantics.** Intervals are treated as CLOSED on both ends: `(a, b)` represents every integer from `a` to `b` inclusive. Two intervals merge into one if:
- Their ranges overlap at any integer, OR
- Their endpoints touch: `(1, 3)` and `(3, 5)` merge into `(1, 5)`.
- Their endpoints are adjacent: `(1, 3)` and `(4, 5)` stay separate (no integer is shared, and `3` and `4` are distinct).

When multiple intervals merge, the result spans from the minimum start to the maximum end.

**C4. Zero-length intervals.** `(k, k)` is a valid interval representing the single integer `k`. Zero-length intervals participate in merging the same way: `(3, 3)` merges with `(1, 5)` into `(1, 5)`, and `(3, 3)` alone in the output stays as `(3, 3)`.

**C5. Empty input.** `merge([])` returns `[]`.

**C6. No mutation.** `merge` does not mutate its input list or any of the tuples inside it. Callers can rely on their list being unchanged after the call.

## Notes

- The function operates on integers only. Float inputs are outside the spec.
- `merge([(5, 1)])` must raise `ValueError`, not return `[(1, 5)]`.
