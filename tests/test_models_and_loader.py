from __future__ import annotations

import json
from decimal import Decimal

import pytest
from pydantic import ValidationError

from invoice_generator.loader import load_invoice_config, load_json
from invoice_generator.models import BusinessConfig, InvoiceConfig


def test_valid_business_and_invoice_data(
    valid_business_data: dict[str, object], valid_invoice_data: dict[str, object]
) -> None:
    business = BusinessConfig.model_validate(valid_business_data)
    invoice = InvoiceConfig.model_validate(valid_invoice_data)

    assert business.currency == "ZAR"
    assert invoice.items[0].unit_price == Decimal("100.00")


def test_invoice_requires_invoice_number(valid_invoice_data: dict[str, object]) -> None:
    valid_invoice_data.pop("invoice_number")

    with pytest.raises(ValidationError):
        InvoiceConfig.model_validate(valid_invoice_data)


def test_invoice_rejects_due_date_before_issue_date(
    valid_invoice_data: dict[str, object],
) -> None:
    valid_invoice_data["due_date"] = "2026-10-12"

    with pytest.raises(ValidationError, match="due_date"):
        InvoiceConfig.model_validate(valid_invoice_data)


@pytest.mark.parametrize("value", ["NaN", "Infinity", "-Infinity"])
@pytest.mark.parametrize("field", ["quantity", "unit_price"])
def test_line_items_reject_non_finite_decimal_strings(
    valid_invoice_data: dict[str, object], field: str, value: str
) -> None:
    valid_invoice_data["items"][0][field] = value

    with pytest.raises(ValidationError, match="finite decimal"):
        InvoiceConfig.model_validate(valid_invoice_data)


@pytest.mark.parametrize("value", ["NaN", "Infinity", "-Infinity"])
def test_discount_rejects_non_finite_decimal_strings(
    valid_invoice_data: dict[str, object], value: str
) -> None:
    valid_invoice_data["discount"] = {"type": "fixed", "amount": value}

    with pytest.raises(ValidationError, match="finite decimal"):
        InvoiceConfig.model_validate(valid_invoice_data)


def test_invoice_rejects_empty_item_list(valid_invoice_data: dict[str, object]) -> None:
    valid_invoice_data["items"] = []

    with pytest.raises(ValidationError, match="at least 1 item"):
        InvoiceConfig.model_validate(valid_invoice_data)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("quantity", "0", "quantity"),
        ("unit_price", "-0.01", "unit_price"),
        ("unit_price", 100.0, "decimal string"),
    ],
)
def test_line_item_validation(
    valid_invoice_data: dict[str, object], field: str, value: object, message: str
) -> None:
    items = valid_invoice_data["items"]
    assert isinstance(items, list)
    items[0][field] = value  # type: ignore[index]

    with pytest.raises(ValidationError, match=message):
        InvoiceConfig.model_validate(valid_invoice_data)


@pytest.mark.parametrize(
    "discount",
    [
        {"type": "fixed", "amount": "-1"},
        {"type": "percentage", "amount": "100.01"},
        {"type": "percentage", "amount": "not-a-number"},
    ],
)
def test_discount_validation(
    valid_invoice_data: dict[str, object], discount: object
) -> None:
    valid_invoice_data["discount"] = discount

    with pytest.raises(ValidationError):
        InvoiceConfig.model_validate(valid_invoice_data)


def test_invoice_rejects_vat_fields(valid_invoice_data: dict[str, object]) -> None:
    valid_invoice_data["vat_rate"] = "15"

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        InvoiceConfig.model_validate(valid_invoice_data)


def test_loads_valid_json_file(tmp_path) -> None:
    source = tmp_path / "invoice.json"
    source.write_text(json.dumps({"invoice_number": "INV-TEST"}), encoding="utf-8")

    assert load_json(source) == {"invoice_number": "INV-TEST"}


def test_rejects_invalid_json_file(tmp_path) -> None:
    source = tmp_path / "invoice.json"
    source.write_text("{not json", encoding="utf-8")

    with pytest.raises(ValueError, match="Invalid JSON"):
        load_json(source)


def test_loads_sanitised_invoice_example() -> None:
    invoice = load_invoice_config("data/invoice.example.json")

    assert invoice.invoice_number == "INV-EXAMPLE-001"
