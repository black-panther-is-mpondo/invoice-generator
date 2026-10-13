"""Decimal-based invoice calculations independent from presentation code."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from .models import InvoiceConfig, LineItem

MONEY_PLACES = Decimal("0.01")
ZERO = Decimal("0")


def round_money(value: Decimal) -> Decimal:
    """Round a monetary value to cents using conventional half-up rounding."""
    return value.quantize(MONEY_PLACES, rounding=ROUND_HALF_UP)


@dataclass(frozen=True, slots=True)
class CalculatedLineItem:
    item: LineItem
    total: Decimal


@dataclass(frozen=True, slots=True)
class InvoiceCalculation:
    line_items: tuple[CalculatedLineItem, ...]
    subtotal: Decimal
    discount_total: Decimal
    total_payable: Decimal


def calculate_invoice(invoice: InvoiceConfig) -> InvoiceCalculation:
    """Calculate payable invoice amounts without VAT or rendering concerns."""
    line_items = tuple(
        CalculatedLineItem(
            item=item, total=round_money(item.quantity * item.unit_price)
        )
        for item in invoice.items
    )
    subtotal = round_money(sum((line.total for line in line_items), start=ZERO))
    discount_total = _calculate_discount(invoice, subtotal)
    total_payable = round_money(subtotal - discount_total)

    return InvoiceCalculation(
        line_items=line_items,
        subtotal=subtotal,
        discount_total=discount_total,
        total_payable=total_payable,
    )


def _calculate_discount(invoice: InvoiceConfig, subtotal: Decimal) -> Decimal:
    if invoice.discount is None:
        return ZERO

    if invoice.discount.type == "fixed":
        discount_total = round_money(invoice.discount.amount)
        if discount_total > subtotal:
            raise ValueError("Fixed discount cannot exceed the invoice subtotal.")
        return discount_total

    return round_money(subtotal * invoice.discount.amount / Decimal("100"))
