# Bug Catalog — Assignment 3

Released at the Phase 1 deadline. Lists the twenty labeled bugs (A1 through A20) seeded across the three modules. The three hidden gold-tier bugs are NOT listed here; they surface only in the grading harness's hidden-catch column.

Bugs are identified by opaque IDs to keep the names independent of the spec clauses and of any test names you may have written. Each entry names the module, the spec clause it violates, and a short description. Use this to orient yourself for Phase 2 and to check which bugs your Phase 1 suite caught.

## `lru_cache`

| ID | Clause | What the bug does |
|---|---|---|
| A1 | C5 | `get` returns the value but doesn't move the entry to most-recently-used position. |
| A2 | C6 | `get` returns stale values past their TTL; expiration is only checked at the next `put`. |
| A3 | C7 | `len()` includes entries whose TTL has already passed. |
| A4 | C3 | Re-putting an existing key updates the value but retains the old expiration. |
| A5 | C4 | Cache holds `capacity + 1` entries before evicting. |
| A6 | C1 | `LRUCache(0)` or `LRUCache(-n)` does not raise. |

## `interval_merger`

| ID | Clause | What the bug does |
|---|---|---|
| A7 | C3 | `(1, 3)` and `(3, 5)` stay separate instead of merging. |
| A8 | C4 | Zero-length intervals like `(3, 3)` are filtered out of the result. |
| A9 | C6 | Sorts the input list in place, leaving the caller's list reordered. |
| A10 | C5 | `merge([])` returns `None` instead of `[]`. |
| A11 | C2 | Output is returned in input-appearance order rather than sorted ascending. |
| A12 | C1 | `merge([(5, 3)])` silently swaps endpoints instead of raising. |

## `cart`

| ID | Clause | What the bug does |
|---|---|---|
| A13 | C4 | `SAVE10` and `SAVE20` can both apply; their rates accumulate. |
| A14 | C5 | `FLAT5` is subtracted before the percent discount instead of after. |
| A15 | C5 | Pre-shipping total is allowed to go negative when `FLAT5` exceeds the subtotal. |
| A16 | C5 | `FREESHIP` requires strictly greater than 5000 cents, not `>=`. |
| A17 | C3 | BOGO gives `(qty - 1) // 2` units free instead of `qty // 2`. |
| A18 | C6 | Percent discounts round half-up instead of half-even. |
| A19 | C2 | `apply_code("save10")` succeeds. |
| A20 | C7 | Empty cart is charged shipping. |

## Notes

- The three hidden bugs (H1 through H3) are not enumerated. One exists per module. Each corresponds to a behavior the spec calls for but that's easy to skip past if you only tested the obvious interpretation of a clause. Gold-tier submissions catch them.
- Internal bug identifiers used inside the grading harness are distinct from these student-facing IDs. When the AI reviewer or individual student report mentions an internal name, this catalog is the translation to the opaque ID.
