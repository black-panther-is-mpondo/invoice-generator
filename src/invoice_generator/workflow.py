"""Application-level orchestration for invoice generation entrypoints."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .calculations import InvoiceCalculation, calculate_invoice
from .loader import load_business_config, load_invoice_config
from .models import BusinessConfig, InvoiceConfig
from .payment_receipts import DEFAULT_PAYMENT_RECORD_DIR, create_payment_record
from .renderer import render_invoice


@dataclass(frozen=True, slots=True)
class PreparedInvoice:
    """Validated invoice inputs together with their calculated totals."""

    business: BusinessConfig
    invoice: InvoiceConfig
    calculation: InvoiceCalculation


def prepare_invoice(
    business_path: str | Path = "data/business.json",
    invoice_path: str | Path = "data/invoice.json",
) -> PreparedInvoice:
    """Load, validate, and calculate an invoice without rendering it."""
    business = load_business_config(business_path)
    invoice = load_invoice_config(invoice_path)
    return PreparedInvoice(
        business=business,
        invoice=invoice,
        calculation=calculate_invoice(invoice),
    )


def generate_invoice(
    prepared: PreparedInvoice,
    output_dir: str | Path = "output",
    *,
    prototype: bool = False,
    payment_record_dir: str | Path = DEFAULT_PAYMENT_RECORD_DIR,
) -> Path:
    """Render an invoice and atomically retain its immutable payment snapshot."""
    destination = render_invoice(
        prepared.business,
        prepared.invoice,
        prepared.calculation,
        output_dir,
        prototype=prototype,
    )
    create_payment_record(
        prepared.business,
        prepared.invoice,
        prepared.calculation,
        payment_record_dir,
    )
    return destination
