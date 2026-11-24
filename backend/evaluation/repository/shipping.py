"""Delivery fee rules for the evaluation shop."""

FREE_SHIPPING_THRESHOLD = 50
STANDARD_SHIPPING_FEE = 5


def shipping_fee(subtotal: int) -> int:
    if subtotal >= FREE_SHIPPING_THRESHOLD:
        return 0
    return STANDARD_SHIPPING_FEE
