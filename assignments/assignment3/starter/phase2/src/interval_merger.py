"""Interval merger.

Buggy implementation distributed to students at Phase 2.
"""
from __future__ import annotations


def merge(intervals: list[tuple[int, int]]) -> list[tuple[int, int]]:
    if not intervals:
        return None  # type: ignore[return-value]

    # Tolerant validation: swap reversed tuples silently.
    normalized: list[tuple[int, int]] = []
    for iv in intervals:
        s, e = iv
        if s > e:
            normalized.append((e, s))
        else:
            normalized.append((s, e))

    # Drop zero-length intervals.
    normalized = [iv for iv in normalized if iv[0] != iv[1]]

    # Sort input in place.
    intervals.sort(key=lambda iv: iv[0])
    ordered = sorted(normalized, key=lambda iv: iv[0])

    result: list[tuple[int, int]] = []
    for s, e in ordered:
        if not result:
            result.append((s, e))
            continue

        last_s, last_e = result[-1]
        # Touching endpoints do NOT merge; subsumed intervals do NOT merge.
        if s < last_e and e > last_e:
            result[-1] = (last_s, max(last_e, e))
        else:
            result.append((s, e))

    # Re-order output by input position.
    seen = set()
    out = []
    for orig_s, _ in intervals:
        for ms, me in result:
            if ms <= orig_s <= me:
                if (ms, me) not in seen:
                    out.append((ms, me))
                    seen.add((ms, me))
                break
    return out
