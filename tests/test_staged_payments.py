from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError
from pypdf import PdfReader

from invoice_generator.models import InvoiceConfig
from invoice_generator.staged_payments import (
    StagedProject,
    create_deposit_invoice,
    create_final_balance_invoice,
    load_staged_project,
    record_deposit_payment,
    record_final_balance_payment,
    save_staged_project,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BUSINESS_EXAMPLE = PROJECT_ROOT / "data" / "business.example.json"


def _project_data(
    *,
    total: str = "3500.00",
    deposit_percentage: str = "50",
) -> dict[str, object]:
    return {
        "project_id": "example-website-2026",
        "customer_reference": "example-client",
        "customer": {
            "name": "Example Client",
            "email": "client@example.com",
            "phone": "+1 555 010 0100",
        },
        "service_description": "Website design and development",
        "project_total": total,
        "deposit_percentage": deposit_percentage,
        "deposit_invoice_number": None,
        "deposit_status": "not_invoiced",
        "deposit_payment": None,
        "final_invoice_number": None,
        "final_invoice_status": "not_invoiced",
    }


def _write_invoice_template(
    tmp_path: Path, valid_invoice_data: dict[str, object], number: str = "INV-DEP-001"
) -> Path:
    valid_invoice_data["invoice_number"] = number
    source = tmp_path / f"{number}.json"
    source.write_text(json.dumps(valid_invoice_data), encoding="utf-8")
    return source


def _write_project(tmp_path: Path, project: StagedProject | None = None) -> Path:
    path = tmp_path / "projects" / "example-website-2026.json"
    save_staged_project(project or StagedProject.model_validate(_project_data()), path)
    return path


def _create_deposit(
    tmp_path: Path, valid_invoice_data: dict[str, object]
) -> tuple[Path, Path]:
    project_path = _write_project(tmp_path)
    template_path = _write_invoice_template(tmp_path, valid_invoice_data)
    output = create_deposit_invoice(
        project_path,
        template_path,
        BUSINESS_EXAMPLE,
        tmp_path / "output",
        tmp_path / "payment-records",
    )
    return project_path, output


def test_calculates_current_project_deposit_and_balance() -> None:
    project = StagedProject.model_validate(_project_data())

    assert project.deposit_amount == Decimal("1750.00")
    assert project.remaining_balance == Decimal("1750.00")


@pytest.mark.parametrize(
    ("total", "percentage", "deposit", "balance"),
    [
        ("6000.00", "50", "3000.00", "3000.00"),
        ("10000.00", "30", "3000.00", "7000.00"),
        ("2500.00", "40", "1000.00", "1500.00"),
        ("100.01", "33.33", "33.33", "66.68"),
    ],
)
def test_calculates_other_deposit_percentages_with_money_rounding(
    total: str, percentage: str, deposit: str, balance: str
) -> None:
    project = StagedProject.model_validate(
        _project_data(total=total, deposit_percentage=percentage)
    )

    assert project.deposit_amount == Decimal(deposit)
    assert project.remaining_balance == Decimal(balance)


@pytest.mark.parametrize("percentage", ["0", "100", "-1", "100.01"])
def test_rejects_invalid_deposit_percentages(percentage: str) -> None:
    with pytest.raises(ValidationError, match="deposit_percentage"):
        StagedProject.model_validate(_project_data(deposit_percentage=percentage))


def test_requires_staged_customer_email() -> None:
    data = _project_data()
    customer = data["customer"]
    assert isinstance(customer, dict)
    customer["email"] = ""

    with pytest.raises(ValidationError, match="customer.email"):
        StagedProject.model_validate(data)


def test_creates_unpaid_deposit_invoice_and_persists_it(
    tmp_path: Path, valid_invoice_data: dict[str, object]
) -> None:
    project_path, output = _create_deposit(tmp_path, valid_invoice_data)
    project = load_staged_project(project_path)
    text = "\n".join(page.extract_text() for page in PdfReader(output).pages)

    assert output.name == "INV-DEP-001.pdf"
    assert project.deposit_invoice_number == "INV-DEP-001"
    assert project.deposit_status == "unpaid"
    assert project.deposit_payment is None
    assert "R 1,750.00" in text
    assert "Full agreed project value" in text
    assert (
        "The deposit is required before website design and development begins"
        in " ".join(text.split())
    )


def test_rejects_duplicate_deposit_invoice_creation(
    tmp_path: Path, valid_invoice_data: dict[str, object]
) -> None:
    project_path, _ = _create_deposit(tmp_path, valid_invoice_data)
    template_path = _write_invoice_template(tmp_path, valid_invoice_data)

    with pytest.raises(ValueError, match="already been created"):
        create_deposit_invoice(
            project_path, template_path, BUSINESS_EXAMPLE, tmp_path / "output"
        )


def test_records_full_deposit_once_and_persists_across_sessions(
    tmp_path: Path, valid_invoice_data: dict[str, object]
) -> None:
    project_path, _ = _create_deposit(tmp_path, valid_invoice_data)

    recorded = record_deposit_payment(
        project_path,
        "INV-DEP-001",
        "1750.00",
        date(2026, 10, 13),
        "PAYMENT-EXAMPLE-001",
        tmp_path / "payment-records",
    )
    reloaded = load_staged_project(project_path)

    assert recorded.deposit_status == "paid"
    assert reloaded.deposit_payment is not None
    assert reloaded.deposit_payment.amount_received == Decimal("1750.00")
    assert reloaded.deposit_payment.payment_reference == "PAYMENT-EXAMPLE-001"

    with pytest.raises(ValueError, match="already been recorded"):
        record_deposit_payment(
            project_path,
            "INV-DEP-001",
            "1750.00",
            "2026-10-13",
            payment_record_dir=tmp_path / "payment-records",
        )


def test_rejects_partial_or_mismatched_deposit_payment(
    tmp_path: Path, valid_invoice_data: dict[str, object]
) -> None:
    project_path, _ = _create_deposit(tmp_path, valid_invoice_data)

    with pytest.raises(ValueError, match="full deposit"):
        record_deposit_payment(
            project_path,
            "INV-DEP-001",
            "1000.00",
            "2026-10-13",
            payment_record_dir=tmp_path / "payment-records",
        )
    with pytest.raises(ValueError, match="does not match"):
        record_deposit_payment(
            project_path,
            "INV-WRONG-001",
            "1750.00",
            "2026-10-13",
            payment_record_dir=tmp_path / "payment-records",
        )


def test_prevents_final_invoice_before_full_deposit_payment(
    tmp_path: Path, valid_invoice_data: dict[str, object]
) -> None:
    project_path, _ = _create_deposit(tmp_path, valid_invoice_data)

    with pytest.raises(ValueError, match="Confirm the full deposit"):
        create_final_balance_invoice(
            project_path,
            "INV-FINAL-001",
            "2026-10-14",
            BUSINESS_EXAMPLE,
            tmp_path / "output",
        )


def test_creates_final_balance_after_confirmed_deposit(
    tmp_path: Path, valid_invoice_data: dict[str, object]
) -> None:
    project_path, deposit_output = _create_deposit(tmp_path, valid_invoice_data)
    record_deposit_payment(
        project_path,
        "INV-DEP-001",
        "1750.00",
        "2026-10-13",
        payment_record_dir=tmp_path / "payment-records",
    )

    final_output = create_final_balance_invoice(
        project_path,
        "INV-FINAL-001",
        "2026-10-14",
        BUSINESS_EXAMPLE,
        tmp_path / "output",
        tmp_path / "payment-records",
    )
    project = load_staged_project(project_path)
    text = "\n".join(page.extract_text() for page in PdfReader(final_output).pages)

    assert deposit_output.name != final_output.name
    assert project.final_invoice_number == "INV-FINAL-001"
    assert project.final_invoice_status == "unpaid"
    assert "16 October 2026" in text
    assert "final outstanding balance" in " ".join(text.split())
    assert "deposit invoice INV-DEP-001" in text
    assert "R 1,750.00" in text

    with pytest.raises(ValueError, match="already been created"):
        create_final_balance_invoice(
            project_path,
            "INV-FINAL-002",
            "2026-10-14",
            BUSINESS_EXAMPLE,
            tmp_path / "output",
        )


def test_rejects_final_invoice_number_matching_the_deposit(
    tmp_path: Path, valid_invoice_data: dict[str, object]
) -> None:
    project_path, _ = _create_deposit(tmp_path, valid_invoice_data)
    record_deposit_payment(
        project_path,
        "INV-DEP-001",
        "1750.00",
        "2026-10-13",
        payment_record_dir=tmp_path / "payment-records",
    )

    with pytest.raises(ValueError, match="must differ"):
        create_final_balance_invoice(
            project_path,
            "INV-DEP-001",
            "2026-10-14",
            BUSINESS_EXAMPLE,
            tmp_path / "output",
        )


def test_records_full_final_balance_payment(
    tmp_path: Path, valid_invoice_data: dict[str, object]
) -> None:
    project_path, _ = _create_deposit(tmp_path, valid_invoice_data)
    records = tmp_path / "payment-records"
    record_deposit_payment(
        project_path,
        "INV-DEP-001",
        "1750.00",
        "2026-10-13",
        payment_record_dir=records,
    )
    create_final_balance_invoice(
        project_path,
        "INV-FINAL-001",
        "2026-10-14",
        BUSINESS_EXAMPLE,
        tmp_path / "output",
        records,
    )

    project = record_final_balance_payment(
        project_path,
        "INV-FINAL-001",
        "1750.00",
        "2026-10-16",
        payment_record_dir=records,
    )

    assert project.final_invoice_status == "paid"
    assert project.final_payment is not None
    assert project.final_payment.amount_received == Decimal("1750.00")


def test_deposit_template_customer_must_match_project(
    tmp_path: Path, valid_invoice_data: dict[str, object]
) -> None:
    project_path = _write_project(tmp_path)
    valid_invoice_data["customer"] = {
        "name": "Different Client",
        "email": "different@example.com",
        "phone": "",
    }
    template_path = _write_invoice_template(tmp_path, valid_invoice_data)

    with pytest.raises(ValueError, match="must match"):
        create_deposit_invoice(
            project_path, template_path, BUSINESS_EXAMPLE, tmp_path / "output"
        )


def test_existing_invoice_output_is_not_overwritten(
    tmp_path: Path, valid_invoice_data: dict[str, object]
) -> None:
    project_path = _write_project(tmp_path)
    template_path = _write_invoice_template(tmp_path, valid_invoice_data)
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    existing = output_dir / "INV-DEP-001.pdf"
    existing.write_bytes(b"existing invoice")

    with pytest.raises(FileExistsError, match="already exists"):
        create_deposit_invoice(
            project_path, template_path, BUSINESS_EXAMPLE, output_dir
        )
    assert load_staged_project(project_path).deposit_invoice_number is None
    assert existing.read_bytes() == b"existing invoice"


def test_preserves_ordinary_invoice_model_validation(
    valid_invoice_data: dict[str, object],
) -> None:
    invoice = InvoiceConfig.model_validate(valid_invoice_data)

    assert invoice.invoice_number == "INV-001"
