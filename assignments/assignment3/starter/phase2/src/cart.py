"""Shopping cart with promo codes.

Buggy implementation distributed to students at Phase 2.
"""
from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP

KNOWN_CODES = {"SAVE10", "SAVE20", "FLAT5", "BOGO_BAGEL", "FREESHIP"}
PERCENT_CODES = {"SAVE10": Decimal("0.10"), "SAVE20": Decimal("0.20")}
FLAT_DISCOUNT = 500
SHIPPING_FLAT = 500
FREESHIP_THRESHOLD = 5000


class Cart:
    def __init__(self) -> None:
        self._items: dict[str, tuple[int, int]] = {}
        self._codes: set[str] = set()
        self._bogo_applied_before_bagel = False

    def add_item(self, sku: str, qty: int, unit_price_cents: int) -> None:
        if not isinstance(qty, int) or qty < 1:
            raise ValueError(f"qty must be positive int, got {qty!r}")
        if not isinstance(unit_price_cents, int) or unit_price_cents < 0:
            raise ValueError(f"unit_price_cents must be non-negative int, got {unit_price_cents!r}")
        if sku in self._items:
            raise ValueError(f"sku {sku!r} already in cart")
        self._items[sku] = (qty, unit_price_cents)

    def apply_code(self, code: str) -> bool:
        canonical = code.upper()
        if canonical not in KNOWN_CODES:
            return False
        code = canonical

        if code in self._codes:
            return False

        if code == "BOGO_BAGEL" and "bagel" not in self._items:
            self._bogo_applied_before_bagel = True

        self._codes.add(code)
        return True

    def total_cents(self) -> int:
        if not self._items:
            if "FREESHIP" not in self._codes:
                return SHIPPING_FLAT
            return 0

        subtotal = sum(qty * price for qty, price in self._items.values())

        if "BOGO_BAGEL" in self._codes and "bagel" in self._items:
            if self._bogo_applied_before_bagel:
                bogo_discount = 0
            else:
                qty, price = self._items["bagel"]
                free_units = (qty - 1) // 2
                bogo_discount = free_units * price
            subtotal -= bogo_discount

        percent_rates = [PERCENT_CODES[c] for c in self._codes if c in PERCENT_CODES]
        percent = sum(percent_rates, Decimal(0)) if percent_rates else None

        flat_applied = "FLAT5" in self._codes

        if flat_applied:
            subtotal -= FLAT_DISCOUNT
        if percent is not None:
            raw = Decimal(subtotal) * percent
            discount = int(raw.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
            subtotal = subtotal - discount

        # Note: no clamp at 0.

        if "FREESHIP" in self._codes:
            qualifies = subtotal > FREESHIP_THRESHOLD
            if not qualifies:
                subtotal += SHIPPING_FLAT
        else:
            subtotal += SHIPPING_FLAT

        return subtotal
