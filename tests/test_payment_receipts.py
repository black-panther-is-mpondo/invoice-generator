from __future__ import annotations

import json
from pathlib import Path

import pytest
from pypdf import PdfReader

import invoice_generator.payment_receipts as payment_receipts
from invoice_generator import (
    create_deposit_invoice,
    create_receipt,
    generate_invoice,
    load_payment_record,
    record_deposit_payment,
    record_full_payment,
)
from invoice_generator.calculations import calculate_invoice
from invoice_generator.models import BusinessConfig, InvoiceConfig
from invoice_generator.staged_payments import StagedProject, save_staged_project
from invoice_generator.workflow import PreparedInvoice


def _prepared(
    business_data: dict[str, object], invoice_data: dict[str, object], number: str
) -> PreparedInvoice:
    business = BusinessConfig.model_validate(business_data)
    invoice = InvoiceConfig.model_validate(invoice_data | {"invoice_number": number})
    return PreparedInvoice(business, invoice, calculate_invoice(invoice))


def _project_data() -> dict[str, object]:
    return {
        "project_id": "fictional-website-2026",
        "customer_reference": "fictional-client",
        "customer": {
            "name": "Example Client",
            "email": "client@example.com",
            "phone": "+1 555 010 0100",
        },
        "service_description": "Website design and development",
        "project_total": "3500.00",
        "deposit_percentage": "50",
        "deposit_invoice_number": None,
        "deposit_status": "not_invoiced",
        "deposit_payment": None,
        "final_invoice_number": None,
        "final_invoice_status": "not_invoiced",
        "final_payment": None,
    }


def test_records_full_payment_and_renders_one_page_receipt(
    valid_business_data: dict[str, object],
    valid_invoice_data: dict[str, object],
    tmp_path: Path,
) -> None:
    prepared = _prepared(valid_business_data, valid_invoice_data, "INV-RECEIPT-001")
    records = tmp_path / "records"
    output = tmp_path / "output"

    generate_invoice(prepared, output, payment_record_dir=records)
    snapshot = load_payment_record(records, "INV-RECEIPT-001")
    assert snapshot.snapshot.total_payable == prepared.calculation.total_payable
    assert snapshot.payment is None

    with pytest.raises(ValueError, match="full invoice amount"):
        record_full_payment(records, "INV-RECEIPT-001", "99.99", "2026-10-14")

    record_full_payment(
        records,
        "INV-RECEIPT-001",
        "100.00",
        "2026-10-14",
        "FICTIONAL-PAYMENT-001",
    )
    receipt = create_receipt(records, "INV-RECEIPT-001", output)
    reader = PdfReader(receipt)
    text = " ".join(page.extract_text() for page in reader.pages)

    assert len(reader.pages) == 1
    assert receipt.name == "RCT-000001.pdf"
    assert "RECEIPT" in text
    assert "INV-RECEIPT-001" in text
    assert "R 100.00" in text
    assert "FICTIONAL-PAYMENT-001" in text


def test_failed_receipt_render_reuses_its_assigned_number(
    valid_business_data: dict[str, object],
    valid_invoice_data: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    prepared = _prepared(valid_business_data, valid_invoice_data, "INV-RETRY-001")
    records = tmp_path / "records"
    output = tmp_path / "output"
    generate_invoice(prepared, output, payment_record_dir=records)
    record_full_payment(records, "INV-RETRY-001", "100.00", "2026-10-14")

    original_render = payment_receipts.render_receipt

    def fail_render(*args: object, **kwargs: object) -> Path:
        raise RuntimeError("intentional receipt render failure")

    monkeypatch.setattr(payment_receipts, "render_receipt", fail_render)
    with pytest.raises(RuntimeError, match="intentional receipt render failure"):
        create_receipt(records, "INV-RETRY-001", output)

    assigned = load_payment_record(records, "INV-RETRY-001").receipt_number
    monkeypatch.setattr(payment_receipts, "render_receipt", original_render)
    receipt = create_receipt(records, "INV-RETRY-001", output)

    assert assigned == "RCT-000001"
    assert receipt.name == f"{assigned}.pdf"
    assert load_payment_record(records, "INV-RETRY-001").receipt_number == assigned


def test_staged_deposit_receipt_describes_the_deposit_only(
    valid_invoice_data: dict[str, object], tmp_path: Path
) -> None:
    project_path = tmp_path / "project.json"
    invoice_path = tmp_path / "deposit-template.json"
    records = tmp_path / "records"
    output = tmp_path / "output"
    save_staged_project(StagedProject.model_validate(_project_data()), project_path)
    invoice_path.write_text(
        json.dumps(valid_invoice_data | {"invoice_number": "INV-DEPOSIT-RECEIPT"}),
        encoding="utf-8",
    )
    business_path = (
        Path(__file__).resolve().parents[1] / "data" / "business.example.json"
    )

    create_deposit_invoice(project_path, invoice_path, business_path, output, records)
    record_deposit_payment(
        project_path,
        "INV-DEPOSIT-RECEIPT",
        "1750.00",
        "2026-10-14",
        payment_record_dir=records,
    )
    receipt = create_receipt(records, "INV-DEPOSIT-RECEIPT", output)
    text = " ".join(page.extract_text() for page in PdfReader(receipt).pages)

    assert "Upfront deposit for Website design and development" in text
    assert "R 1,750.00" in text
    assert "R 3,500.00" not in text
