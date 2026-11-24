"""Calculate an order total from its subtotal and delivery fee."""

from shipping import shipping_fee


def order_total(subtotal: int) -> int:
    return subtotal + shipping_fee(subtotal)
