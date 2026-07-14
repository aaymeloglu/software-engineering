# `cart` — Specification

Shopping cart with promo codes. All monetary values are integer cents.

## Public API

```python
from cart import Cart

class Cart:
    def __init__(self) -> None: ...
    def add_item(self, sku: str, qty: int, unit_price_cents: int) -> None: ...
    def apply_code(self, code: str) -> bool: ...
    def total_cents(self) -> int: ...
```

## Behavior

**C1. `add_item(sku, qty, unit_price_cents)`.**
- `qty` must be a positive integer (>= 1). Invalid `qty` raises `ValueError`.
- `unit_price_cents` must be a non-negative integer. Invalid `unit_price_cents` raises `ValueError`.
- Adding an item whose `sku` is already in the cart raises `ValueError`. One line item per SKU.

**C2. `apply_code(code)`.**
- Returns `True` if the code was applied.
- Returns `False` if the code is unknown, is already applied, or conflicts with an applied code (see C4).
- Code names are case-sensitive. `"SAVE10"` is a valid code; `"save10"` is unknown.

**C3. Known codes.**
- `"SAVE10"` — 10% off subtotal (after BOGO).
- `"SAVE20"` — 20% off subtotal (after BOGO).
- `"FLAT5"` — 500 cents off, applied AFTER any percent discount.
- `"BOGO_BAGEL"` — for the line item with sku `"bagel"`, `(qty // 2)` units are free. (If no bagel line item exists when `total_cents` is computed, the code has no effect but is still considered "applied" for the purpose of C2's duplicate-application rule.)
- `"FREESHIP"` — waives the flat 500-cent shipping charge when the post-discount pre-shipping subtotal is `>= 5000` cents.

**C4. Stacking rules.**
- `SAVE10` and `SAVE20` are mutually exclusive. Applying one then the other returns `False` on the second call; only the first takes effect.
- `FLAT5` stacks with either percent code.
- `BOGO_BAGEL` stacks with every other code.
- `FREESHIP` stacks with every other code.

**C5. Application order for `total_cents`.**
1. Compute subtotal from line items.
2. Subtract `BOGO_BAGEL` discount if applied and bagel line item exists.
3. Apply the percent discount (if any) to the post-BOGO subtotal.
4. Subtract `FLAT5` (500 cents) if applied. If this would make the pre-shipping total negative, clamp at 0.
5. If cart is non-empty, add 500 cents shipping UNLESS `FREESHIP` is applied AND the pre-shipping total (from step 4) is `>= 5000`.
6. If cart is empty, shipping is not added regardless of codes.

**C6. Rounding.** Percent discounts are rounded half-even (banker's rounding) to the nearest cent. Use `decimal.ROUND_HALF_EVEN` or equivalent. Integer arithmetic should be used where possible; rounding only applies to the percent-discount result.

**C7. Empty cart.** `Cart().total_cents()` returns 0 regardless of which codes have been applied. Shipping is not added to an empty cart.

## Notes

- All prices and totals are whole cents. A price of $1.05 is `unit_price_cents=105`.
- Tests may construct subtotals that specifically expose rounding behavior at the half-cent boundary.
