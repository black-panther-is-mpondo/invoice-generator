"""Private payment records and one-page receipt rendering."""

from __future__ import annotations

import json
import re
import time
from datetime import date
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

from pydantic import Field, field_validator, model_validator
from reportlab.pdfgen.canvas import Canvas

from .calculations import InvoiceCalculation
from .layout import (
    CONTENT_WIDTH,
    FONT_BLACK,
    FONT_BOLD,
    FONT_REGULAR,
    FONT_SEMIBOLD,
    FOOTER_MESSAGE_SIZE,
    FOOTER_RULE_Y,
    FOOTER_TEXT_Y,
    HAIRLINE,
    HEADER_CONTACT_SIZE,
    HEADER_DESCRIPTOR_SIZE,
    HEADER_NAME_SIZE,
    INK,
    LEFT,
    MUTED,
    PAGE_HEIGHT,
    PAGE_WIDTH,
    PANEL_CORNER_RADIUS,
    PAYMENT_BOX,
    RIGHT,
    TOP_RULE,
    TOTAL_BOX,
    WORD_SPACING,
)
from .loader import resolve_project_path
from .models import BusinessConfig, InvoiceConfig, InvoiceModel, parse_decimal_string
from .renderer import (
    _draw_logo,
    _line_top,
    _load_logo,
    _rounded_rect_top,
    _text,
    _wordmark_lines,
    format_currency,
    register_lato_fonts,
)

DEFAULT_PAYMENT_RECORD_DIR = "data/payment_records"
DEFAULT_RECEIPT_DIR = "data/receipts"
_SEQUENCE_FILE = "receipt_sequence.json"


class InvoiceSnapshot(InvoiceModel):
    """The immutable issued-invoice values needed for a later payment receipt."""

    business: BusinessConfig
    invoice: InvoiceConfig
    total_payable: Decimal
    payment_purpose: str = Field(min_length=1)
    receipt_status: str = "PAID IN FULL"
    remaining_balance: Decimal = Decimal("0.00")

    @field_validator("total_payable", "remaining_balance", mode="before")
    @classmethod
    def parse_total_payable(cls, value: object) -> Decimal:
        if isinstance(value, Decimal):
            return value
        return parse_decimal_string(value)

    @model_validator(mode="after")
    def validate_total_payable(self) -> InvoiceSnapshot:
        if self.total_payable < 0:
            raise ValueError("total_payable must be non-negative")
        return self


class ConfirmedPayment(InvoiceModel):
    """A manually confirmed, full payment. This never processes a transaction."""

    amount_received: Decimal
    received_date: date
    payment_reference: str | None = None

    @field_validator("amount_received", mode="before")
    @classmethod
    def parse_amount_received(cls, value: object) -> Decimal:
        return parse_decimal_string(value)

    @model_validator(mode="after")
    def validate_amount_received(self) -> ConfirmedPayment:
        if self.amount_received < 0:
            raise ValueError("amount_received must be non-negative")
        return self


class PaymentRecord(InvoiceModel):
    """Private, append-only state for an issued invoice and its receipt."""

    snapshot: InvoiceSnapshot
    payment: ConfirmedPayment | None = None
    receipt_number: str | None = None
    receipt_path: str | None = None

    @model_validator(mode="after")
    def validate_payment(self) -> PaymentRecord:
        if (
            self.payment is not None
            and self.payment.amount_received != self.snapshot.total_payable
        ):
            raise ValueError("A payment record must equal the full invoice amount.")
        if self.receipt_number is not None and self.payment is None:
            raise ValueError("A receipt number requires a confirmed payment.")
        if self.receipt_path is not None and self.receipt_number is None:
            raise ValueError("A receipt path requires an assigned receipt number.")
        return self


def create_payment_record(
    business: BusinessConfig,
    invoice: InvoiceConfig,
    calculation: InvoiceCalculation,
    record_dir: str | Path = DEFAULT_PAYMENT_RECORD_DIR,
    *,
    payment_purpose: str = "Invoice payment",
    receipt_status: str = "PAID IN FULL",
    remaining_balance: Decimal = Decimal("0.00"),
) -> PaymentRecord:
    """Atomically save an invoice snapshot once its invoice PDF has been issued."""
    record = PaymentRecord(
        snapshot=InvoiceSnapshot(
            business=business,
            invoice=invoice,
            total_payable=calculation.total_payable,
            payment_purpose=payment_purpose,
            receipt_status=receipt_status,
            remaining_balance=remaining_balance,
        )
    )
    destination = _record_path(record_dir, invoice.invoice_number)
    if destination.exists():
        existing = load_payment_record(record_dir, invoice.invoice_number)
        if existing.snapshot != record.snapshot:
            raise ValueError(
                "A different immutable payment record already exists for this invoice number."
            )
        return existing
    _write_json_atomic(destination, record.model_dump(mode="json"))
    return record


def load_payment_record(record_dir: str | Path, invoice_number: str) -> PaymentRecord:
    """Load one private payment record by its invoice number."""
    source = _record_path(record_dir, invoice_number)
    try:
        data = json.loads(source.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise FileNotFoundError(
            f"Payment record not found for invoice {invoice_number}: {source}"
        ) from error
    except json.JSONDecodeError as error:
        raise ValueError(f"Invalid JSON in payment record: {source}") from error
    return PaymentRecord.model_validate(data)


def record_full_payment(
    record_dir: str | Path,
    invoice_number: str,
    amount_received: str,
    received_date: str | date,
    payment_reference: str | None = None,
) -> PaymentRecord:
    """Persist a manually confirmed payment only when it settles the invoice exactly."""
    record = load_payment_record(record_dir, invoice_number)
    payment = ConfirmedPayment.model_validate(
        {
            "amount_received": amount_received,
            "received_date": received_date,
            "payment_reference": payment_reference,
        }
    )
    if payment.amount_received != record.snapshot.total_payable:
        raise ValueError("The received amount must equal the full invoice amount.")
    if record.payment is not None:
        if record.payment == payment:
            return record
        raise ValueError("A full payment has already been recorded for this invoice.")
    updated = record.model_copy(update={"payment": payment})
    _write_json_atomic(
        _record_path(record_dir, invoice_number), updated.model_dump(mode="json")
    )
    return updated


def create_receipt(
    record_dir: str | Path,
    invoice_number: str,
    output_dir: str | Path = DEFAULT_RECEIPT_DIR,
) -> Path:
    """Render or recover the single receipt assigned to a confirmed payment."""
    record = load_payment_record(record_dir, invoice_number)
    if record.payment is None:
        raise ValueError("Record a full confirmed payment before creating a receipt.")
    if record.receipt_number is None:
        record = _assign_receipt_number(record_dir, invoice_number)

    destination = _receipt_destination(output_dir, record.receipt_number)
    if destination.is_file():
        if record.receipt_path != str(destination):
            _write_record(
                record_dir,
                invoice_number,
                record.model_copy(update={"receipt_path": str(destination)}),
            )
        return destination
    destination = render_receipt(record, output_dir)
    _write_record(
        record_dir,
        invoice_number,
        record.model_copy(update={"receipt_path": str(destination)}),
    )
    return destination


def render_receipt(
    record: PaymentRecord, output_dir: str | Path = DEFAULT_RECEIPT_DIR
) -> Path:
    """Render a receipt as a separate, fixed one-page A4 PDF."""
    assert record.payment is not None
    assert record.receipt_number is not None
    register_lato_fonts()
    logo, logo_size = _load_logo(record.snapshot.business.business.logo_path)
    destination = _reserve_receipt_destination(output_dir, record.receipt_number)
    try:
        canvas = Canvas(str(destination), pagesize=(PAGE_WIDTH, PAGE_HEIGHT))
        canvas.setTitle(f"Receipt {record.receipt_number}")
        canvas.setAuthor(record.snapshot.business.business.name)
        _draw_receipt(canvas, record, logo, logo_size)
        canvas.save()
    except Exception:
        destination.unlink(missing_ok=True)
        raise
    return destination


def receipt_filename(receipt_number: str) -> str:
    """Return a predictable portable receipt filename."""
    safe_number = re.sub(r"[^A-Za-z0-9._-]+", "-", receipt_number).strip(".-")
    if not safe_number:
        raise ValueError("Receipt number cannot produce an empty filename.")
    return f"{safe_number}.pdf"


def _assign_receipt_number(
    record_dir: str | Path, invoice_number: str
) -> PaymentRecord:
    directory = _record_directory(record_dir)
    directory.mkdir(parents=True, exist_ok=True)
    lock_path = directory / ".receipt-sequence.lock"
    _acquire_lock(lock_path)
    try:
        record = load_payment_record(directory, invoice_number)
        if record.receipt_number is not None:
            return record
        sequence_path = directory / _SEQUENCE_FILE
        next_number = 1
        if sequence_path.exists():
            try:
                sequence = json.loads(sequence_path.read_text(encoding="utf-8"))
                next_number = sequence["next_receipt_number"]
            except (KeyError, TypeError, json.JSONDecodeError) as error:
                raise ValueError(
                    f"Invalid receipt sequence file: {sequence_path}"
                ) from error
        if not isinstance(next_number, int) or next_number < 1:
            raise ValueError(f"Invalid receipt sequence file: {sequence_path}")

        receipt_number = f"RCT-{next_number:06d}"
        updated = record.model_copy(update={"receipt_number": receipt_number})
        _write_json_atomic(
            _record_path(directory, invoice_number), updated.model_dump(mode="json")
        )
        _write_json_atomic(sequence_path, {"next_receipt_number": next_number + 1})
        return updated
    finally:
        lock_path.unlink(missing_ok=True)


def _draw_receipt(canvas: Canvas, record: PaymentRecord, logo, logo_size) -> None:
    snapshot = record.snapshot
    payment = record.payment
    assert payment is not None
    _draw_receipt_header(
        canvas, snapshot.business, record.receipt_number, logo, logo_size
    )
    _text(canvas, LEFT, 197.0, "R E C E I V E D  F R O M", FONT_BOLD, 8.0, MUTED)
    _text(
        canvas,
        LEFT,
        232.0,
        snapshot.invoice.customer.name,
        FONT_BOLD,
        17.48,
        INK,
        word_spacing=WORD_SPACING,
    )
    if snapshot.invoice.customer.email:
        _text(
            canvas,
            LEFT,
            256.0,
            snapshot.invoice.customer.email,
            FONT_REGULAR,
            9.2,
            MUTED,
        )
    _line_top(canvas, 351.0, 191.0, 351.0, 293.0, HAIRLINE, 0.8)
    _text(canvas, 369.0, 195.0, "R E C E I V E D  D A T E", FONT_BOLD, 8.0, MUTED)
    _text(
        canvas,
        369.0,
        219.0,
        payment.received_date.strftime("%d %B %Y"),
        FONT_SEMIBOLD,
        9.57,
        INK,
    )
    _text(canvas, 369.0, 247.0, "I N V O I C E", FONT_BOLD, 8.0, MUTED)
    _text(
        canvas, 369.0, 271.0, snapshot.invoice.invoice_number, FONT_SEMIBOLD, 9.57, INK
    )

    _text(canvas, LEFT, 332.0, "P A Y M E N T  R E C E I V E D", FONT_BLACK, 9.0, INK)
    _line_top(canvas, LEFT, 345.0, RIGHT, 345.0, INK, 1.1)
    _rounded_rect_top(
        canvas, LEFT, 366.0, CONTENT_WIDTH, 170.0, PANEL_CORNER_RADIUS, PAYMENT_BOX
    )
    _text(canvas, 65.0, 396.0, "PAYMENT FOR", FONT_BOLD, 7.6, MUTED)
    _text(
        canvas,
        65.0,
        418.0,
        snapshot.payment_purpose,
        FONT_SEMIBOLD,
        10.12,
        INK,
        word_spacing=WORD_SPACING,
    )
    _text(canvas, 299.0, 396.0, "PAYMENT STATUS", FONT_BOLD, 7.6, MUTED)
    _text(canvas, 299.0, 418.0, snapshot.receipt_status, FONT_SEMIBOLD, 10.12, INK)
    _text(canvas, 65.0, 455.0, "INVOICE TOTAL", FONT_BOLD, 7.6, MUTED)
    _text(
        canvas,
        65.0,
        477.0,
        format_currency(snapshot.total_payable, snapshot.business.currency),
        FONT_SEMIBOLD,
        10.12,
        INK,
    )
    if payment.payment_reference:
        _text(canvas, 299.0, 455.0, "PAYMENT REFERENCE", FONT_BOLD, 7.6, MUTED)
        _text(
            canvas,
            299.0,
            477.0,
            payment.payment_reference,
            FONT_SEMIBOLD,
            10.12,
            INK,
        )
    _line_top(canvas, 65.0, 496.0, 530.28, 496.0, HAIRLINE, 0.8)
    _text(canvas, 65.0, 520.0, "REMAINING BALANCE", FONT_BOLD, 7.6, MUTED)
    _text(
        canvas,
        530.28,
        520.0,
        format_currency(snapshot.remaining_balance, snapshot.business.currency),
        FONT_SEMIBOLD,
        10.12,
        INK,
        right=True,
    )
    _text(
        canvas,
        65.0,
        550.0,
        "This receipt confirms the full payment recorded for this invoice.",
        FONT_REGULAR,
        8.56,
        INK,
        word_spacing=WORD_SPACING,
    )

    _rounded_rect_top(
        canvas, 322.0, 566.0, 225.28, 60.0, PANEL_CORNER_RADIUS, TOTAL_BOX
    )
    _text(canvas, 337.0, 589.0, "AMOUNT RECEIVED", FONT_BOLD, 8.0, INK)
    _text(
        canvas,
        532.28,
        613.0,
        format_currency(payment.amount_received, snapshot.business.currency),
        FONT_BLACK,
        17.85,
        INK,
        right=True,
    )
    _draw_receipt_footer(canvas, snapshot.business)


def _draw_receipt_header(
    canvas: Canvas, business, receipt_number: str, logo, logo_size
) -> None:
    canvas.setFillColor(INK)
    left, top, width, height = TOP_RULE
    canvas.rect(left, PAGE_HEIGHT - top - height, width, height, fill=1, stroke=0)
    _draw_logo(canvas, logo, logo_size)
    primary, descriptor = _wordmark_lines(business.business.name)
    _text(
        canvas,
        136.0,
        90.0,
        primary,
        FONT_BLACK,
        HEADER_NAME_SIZE,
        INK,
        word_spacing=WORD_SPACING,
    )
    _text(canvas, 136.0, 106.0, descriptor, FONT_BOLD, HEADER_DESCRIPTOR_SIZE, INK)
    _text(
        canvas,
        136.0,
        124.0,
        business.business.email,
        FONT_REGULAR,
        HEADER_CONTACT_SIZE,
        MUTED,
    )
    _text(
        canvas,
        136.0,
        139.0,
        f"WhatsApp  {business.business.whatsapp}",
        FONT_REGULAR,
        HEADER_CONTACT_SIZE,
        MUTED,
    )
    _text(canvas, RIGHT, 91.0, "PAYMENT RECEIPT", FONT_BLACK, 24.0, INK, right=True)
    _text(canvas, RIGHT, 115.0, receipt_number, FONT_BOLD, 9.57, INK, right=True)
    _line_top(canvas, LEFT, 162.0, RIGHT, 162.0, HAIRLINE, 0.8)


def _draw_receipt_footer(canvas: Canvas, business) -> None:
    _line_top(canvas, LEFT, FOOTER_RULE_Y, RIGHT, FOOTER_RULE_Y, HAIRLINE, 0.8)
    if business.defaults.footer_message:
        _text(
            canvas,
            LEFT,
            FOOTER_TEXT_Y,
            business.defaults.footer_message,
            FONT_SEMIBOLD,
            FOOTER_MESSAGE_SIZE,
            INK,
            word_spacing=WORD_SPACING,
        )


def _record_directory(record_dir: str | Path) -> Path:
    return resolve_project_path(record_dir)


def _record_path(record_dir: str | Path, invoice_number: str) -> Path:
    safe_number = re.sub(r"[^A-Za-z0-9._-]+", "-", invoice_number).strip(".-")
    if not safe_number:
        raise ValueError(
            "Invoice number cannot produce an empty payment-record filename."
        )
    return _record_directory(record_dir) / f"{safe_number}.json"


def _write_record(
    record_dir: str | Path, invoice_number: str, record: PaymentRecord
) -> None:
    _write_json_atomic(
        _record_path(record_dir, invoice_number), record.model_dump(mode="json")
    )


def _receipt_destination(output_dir: str | Path, receipt_number: str) -> Path:
    return resolve_project_path(output_dir) / receipt_filename(receipt_number)


def _reserve_receipt_destination(output_dir: str | Path, receipt_number: str) -> Path:
    destination = _receipt_destination(output_dir, receipt_number)
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        destination.touch(exist_ok=False)
    except FileExistsError as error:
        raise FileExistsError(f"Receipt PDF already exists: {destination}") from error
    return destination


def _write_json_atomic(destination: Path, data: object) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.{uuid4().hex}.tmp")
    temporary.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    temporary.replace(destination)


def _acquire_lock(lock_path: Path) -> None:
    deadline = time.monotonic() + 5
    while True:
        try:
            lock_path.touch(exist_ok=False)
            return
        except FileExistsError:
            if time.monotonic() >= deadline:
                raise TimeoutError(
                    f"Timed out waiting for receipt sequence lock: {lock_path}"
                ) from None
            time.sleep(0.05)
