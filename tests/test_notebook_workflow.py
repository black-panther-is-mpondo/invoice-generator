from __future__ import annotations

import shutil
from pathlib import Path

import nbformat
import pytest
from nbclient import NotebookClient
from pydantic import ValidationError
from pypdf import PdfReader

from invoice_generator.calculations import calculate_invoice
from invoice_generator.models import InvoiceConfig
from invoice_generator.workflow import (
    PreparedInvoice,
    generate_invoice,
    prepare_invoice,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BUSINESS_EXAMPLE = PROJECT_ROOT / "data" / "business.example.json"
INVOICE_EXAMPLE = PROJECT_ROOT / "data" / "invoice.example.json"
NOTEBOOK_PATH = PROJECT_ROOT / "notebooks" / "create_invoice.ipynb"
STAGED_NOTEBOOK_PATH = PROJECT_ROOT / "notebooks" / "create_staged_invoices.ipynb"
STAGED_PROJECT_EXAMPLE = PROJECT_ROOT / "data" / "staged_project.example.json"


def _prepared_with_number(invoice_number: str) -> PreparedInvoice:
    prepared = prepare_invoice(BUSINESS_EXAMPLE, INVOICE_EXAMPLE)
    invoice = prepared.invoice.model_copy(update={"invoice_number": invoice_number})
    return PreparedInvoice(
        business=prepared.business,
        invoice=invoice,
        calculation=calculate_invoice(invoice),
    )


def test_notebook_is_valid_and_uses_the_workflow() -> None:
    notebook = nbformat.read(NOTEBOOK_PATH, as_version=4)

    nbformat.validate(notebook)
    source = "\n".join(cell.source for cell in notebook.cells)
    assert "prepare_invoice" in source
    assert "generate_invoice" in source
    assert "record_full_payment" in source
    assert "create_receipt" in source
    assert "PROJECT_ROOT" in source
    assert "prototype=False" in source


def test_staged_notebook_is_valid_and_uses_staged_workflow() -> None:
    notebook = nbformat.read(STAGED_NOTEBOOK_PATH, as_version=4)

    nbformat.validate(notebook)
    source = "\n".join(cell.source for cell in notebook.cells)
    assert "create_deposit_invoice" in source
    assert "record_deposit_payment" in source
    assert "create_final_balance_invoice" in source
    assert "record_final_balance_payment" in source
    assert "create_receipt" in source
    assert "INVOICE_STAGED_OPERATION" in source


@pytest.mark.filterwarnings(
    "ignore:Proactor event loop does not implement add_reader family of methods "
    "required for zmq.*:RuntimeWarning"
)
@pytest.mark.parametrize(
    "working_directory", [PROJECT_ROOT, PROJECT_ROOT / "notebooks"]
)
def test_notebook_executes_with_sanitised_configuration(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    working_directory: Path,
) -> None:
    monkeypatch.setenv("INVOICE_BUSINESS_PATH", str(BUSINESS_EXAMPLE))
    monkeypatch.setenv("INVOICE_INVOICE_PATH", str(INVOICE_EXAMPLE))
    monkeypatch.setenv("INVOICE_OUTPUT_DIR", str(tmp_path))
    monkeypatch.setenv("INVOICE_PAYMENT_RECORD_DIR", str(tmp_path / "payment-records"))
    notebook = nbformat.read(NOTEBOOK_PATH, as_version=4)

    NotebookClient(notebook, timeout=120, kernel_name="python3").execute(
        cwd=working_directory
    )

    assert (tmp_path / "INV-EXAMPLE-001.pdf").is_file()


@pytest.mark.filterwarnings(
    "ignore:Proactor event loop does not implement add_reader family of methods "
    "required for zmq.*:RuntimeWarning"
)
def test_staged_notebook_creates_a_sanitised_deposit_invoice(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    project_path = tmp_path / "project.json"
    shutil.copyfile(STAGED_PROJECT_EXAMPLE, project_path)
    monkeypatch.setenv("INVOICE_STAGED_OPERATION", "create_deposit")
    monkeypatch.setenv("INVOICE_STAGED_PROJECT_PATH", str(project_path))
    monkeypatch.setenv("INVOICE_BUSINESS_PATH", str(BUSINESS_EXAMPLE))
    monkeypatch.setenv("INVOICE_DEPOSIT_INVOICE_PATH", str(INVOICE_EXAMPLE))
    monkeypatch.setenv("INVOICE_OUTPUT_DIR", str(tmp_path / "output"))
    monkeypatch.setenv("INVOICE_PAYMENT_RECORD_DIR", str(tmp_path / "payment-records"))
    monkeypatch.setenv("INVOICE_RECEIPT_DIR", str(tmp_path / "receipts"))
    notebook = nbformat.read(STAGED_NOTEBOOK_PATH, as_version=4)

    NotebookClient(notebook, timeout=120, kernel_name="python3").execute(
        cwd=PROJECT_ROOT
    )

    assert (tmp_path / "output" / "INV-EXAMPLE-001.pdf").is_file()


@pytest.mark.filterwarnings(
    "ignore:Proactor event loop does not implement add_reader family of methods "
    "required for zmq.*:RuntimeWarning"
)
def test_ordinary_notebook_creates_a_fictional_receipt(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("INVOICE_BUSINESS_PATH", str(BUSINESS_EXAMPLE))
    monkeypatch.setenv("INVOICE_INVOICE_PATH", str(INVOICE_EXAMPLE))
    monkeypatch.setenv("INVOICE_OUTPUT_DIR", str(tmp_path / "output"))
    monkeypatch.setenv("INVOICE_PAYMENT_RECORD_DIR", str(tmp_path / "payment-records"))
    monkeypatch.setenv("INVOICE_RECEIPT_DIR", str(tmp_path / "receipts"))

    for operation in ("create_invoice", "record_payment", "create_receipt"):
        monkeypatch.setenv("INVOICE_OPERATION", operation)
        if operation == "record_payment":
            monkeypatch.setenv("INVOICE_PAYMENT_AMOUNT", "4500.00")
            monkeypatch.setenv("INVOICE_PAYMENT_DATE", "2026-10-14")
            monkeypatch.setenv(
                "INVOICE_PAYMENT_REFERENCE", "FICTIONAL-NOTEBOOK-PAYMENT"
            )
        notebook = nbformat.read(NOTEBOOK_PATH, as_version=4)
        NotebookClient(notebook, timeout=120, kernel_name="python3").execute(
            cwd=PROJECT_ROOT
        )

    receipt = tmp_path / "receipts" / "RCT-000001.pdf"
    assert receipt.is_file()
    assert len(PdfReader(receipt).pages) == 1


def test_prepare_invoice_loads_sanitised_configuration() -> None:
    prepared = prepare_invoice(BUSINESS_EXAMPLE, INVOICE_EXAMPLE)

    assert prepared.invoice.invoice_number == "INV-EXAMPLE-001"
    assert prepared.calculation.total_payable == prepared.calculation.subtotal


def test_workflow_generates_production_pdf_without_preview_labels(
    tmp_path: Path,
) -> None:
    output = generate_invoice(
        _prepared_with_number("INV-NOTEBOOK-001"),
        tmp_path,
        payment_record_dir=tmp_path / "payment-records",
    )
    text = "\n".join(page.extract_text() for page in PdfReader(output).pages)

    assert output == tmp_path / "INV-NOTEBOOK-001.pdf"
    assert "DESIGN PREVIEW" not in text
    assert "EXAMPLE / 01" not in text


def test_prepare_invoice_reports_missing_configuration(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="Configuration file not found"):
        prepare_invoice(tmp_path / "missing-business.json", INVOICE_EXAMPLE)


def test_prepare_invoice_reports_invalid_invoice_data(tmp_path: Path) -> None:
    invalid_invoice = tmp_path / "invoice.json"
    invalid_invoice.write_text('{"invoice_number": "INV-001"}', encoding="utf-8")

    with pytest.raises(ValidationError):
        prepare_invoice(BUSINESS_EXAMPLE, invalid_invoice)


def test_workflow_creates_output_directory_and_rejects_conflicts(
    tmp_path: Path,
) -> None:
    prepared = _prepared_with_number("INV-NOTEBOOK-002")
    output_dir = tmp_path / "nested" / "output"
    output = generate_invoice(
        prepared, output_dir, payment_record_dir=tmp_path / "payment-records"
    )

    assert output.is_file()
    with pytest.raises(FileExistsError, match="already exists"):
        generate_invoice(
            prepared, output_dir, payment_record_dir=tmp_path / "payment-records"
        )


def test_invalid_model_data_remains_rejected() -> None:
    with pytest.raises(ValidationError):
        InvoiceConfig.model_validate({"invoice_number": "INV-001"})
