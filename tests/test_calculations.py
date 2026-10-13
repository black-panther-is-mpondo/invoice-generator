from __future__ import annotations

from decimal import Decimal

import pytest

from invoice_generator.calculations import calculate_invoice
from invoice_generator.models import InvoiceConfig


def test_calculates_line_totals_without_float_precision_loss(
    valid_invoice_data: dict[str, object],
) -> None:
    valid_invoice_data["items"] = [
        {"description": "Fractional service", "quantity": "3", "unit_price": "0.10"},
        {"description": "Rounded service", "quantity": "1", "unit_price": "1.005"},
    ]

    calculation = calculate_invoice(InvoiceConfig.model_validate(valid_invoice_data))

    assert [line.total for line in calculation.line_items] == [
        Decimal("0.30"),
        Decimal("1.01"),
    ]
    assert calculation.subtotal == Decimal("1.31")
    assert calculation.total_payable == Decimal("1.31")


def test_applies_fixed_discount(valid_invoice_data: dict[str, object]) -> None:
    valid_invoice_data["items"] = [
        {"description": "Service", "quantity": "2", "unit_price": "19.99"}
    ]
    valid_invoice_data["discount"] = {"type": "fixed", "amount": "5.555"}

    calculation = calculate_invoice(InvoiceConfig.model_validate(valid_invoice_data))

    assert calculation.subtotal == Decimal("39.98")
    assert calculation.discount_total == Decimal("5.56")
    assert calculation.total_payable == Decimal("34.42")


def test_applies_percentage_discount(valid_invoice_data: dict[str, object]) -> None:
    valid_invoice_data["discount"] = {"type": "percentage", "amount": "12.5"}

    calculation = calculate_invoice(InvoiceConfig.model_validate(valid_invoice_data))

    assert calculation.discount_total == Decimal("12.50")
    assert calculation.total_payable == Decimal("87.50")


def test_rejects_fixed_discount_greater_than_subtotal(
    valid_invoice_data: dict[str, object],
) -> None:
    valid_invoice_data["discount"] = {"type": "fixed", "amount": "100.01"}

    with pytest.raises(ValueError, match="cannot exceed"):
        calculate_invoice(InvoiceConfig.model_validate(valid_invoice_data))


def test_percentage_discount_at_its_upper_boundary(
    valid_invoice_data: dict[str, object],
) -> None:
    valid_invoice_data["discount"] = {"type": "percentage", "amount": "100"}

    calculation = calculate_invoice(InvoiceConfig.model_validate(valid_invoice_data))

    assert calculation.discount_total == calculation.subtotal
    assert calculation.total_payable == Decimal("0.00")


def test_sums_rounded_line_items_for_repeating_fractional_prices(
    valid_invoice_data: dict[str, object],
) -> None:
    valid_invoice_data["items"] = [
        {"description": "Fractional item", "quantity": "1", "unit_price": "0.335"}
        for _ in range(50)
    ]

    calculation = calculate_invoice(InvoiceConfig.model_validate(valid_invoice_data))

    assert calculation.subtotal == Decimal("17.00")
    assert calculation.total_payable == Decimal("17.00")
