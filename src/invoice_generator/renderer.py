"""ReportLab rendering for validated invoice data and calculated totals."""

from __future__ import annotations

import re
from collections.abc import Iterable
from decimal import Decimal
from importlib.resources import files
from pathlib import Path

from PIL import Image, ImageChops, UnidentifiedImageError
from reportlab.lib.colors import HexColor
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen.canvas import Canvas

from .calculations import CalculatedLineItem, InvoiceCalculation, round_money
from .layout import (
    ACCOUNT_HOLDER_SIZE,
    AMOUNT_RIGHT,
    BILL_TO_LABEL_Y,
    BRAND_DESCRIPTOR_Y,
    BRAND_LEFT,
    BRAND_NAME_Y,
    BUSINESS_EMAIL_Y,
    BUSINESS_WHATSAPP_Y,
    CONTENT_WIDTH,
    CONTINUATION_ITEMS_TITLE_Y,
    CONTINUATION_SUMMARY_TOP,
    CONTINUATION_TABLE_HEADER_TOP,
    CUSTOMER_EMAIL_SIZE,
    CUSTOMER_EMAIL_Y,
    CUSTOMER_EXTRA_SIZE,
    CUSTOMER_EXTRA_Y,
    CUSTOMER_NAME_SIZE,
    CUSTOMER_NAME_Y,
    CUSTOMER_SEPARATOR_BOTTOM,
    CUSTOMER_SEPARATOR_TOP,
    CUSTOMER_SEPARATOR_X,
    DATE_LEFT,
    DESCRIPTION_HEADER_SIZE,
    DESCRIPTION_LEFT,
    DESCRIPTION_RIGHT,
    DESCRIPTION_SIZE,
    DUE_LABEL_Y,
    DUE_VALUE_Y,
    FIRST_ROW_TOP,
    FONT_BLACK,
    FONT_BOLD,
    FONT_REGULAR,
    FONT_SEMIBOLD,
    FOOTER_MESSAGE_SIZE,
    FOOTER_PAGE_SIZE,
    FOOTER_RULE_Y,
    FOOTER_TEXT_Y,
    HAIRLINE,
    HEADER_BOTTOM_RULE_Y,
    HEADER_CONTACT_SIZE,
    HEADER_DESCRIPTOR_SIZE,
    HEADER_NAME_SIZE,
    INK,
    INVOICE_NUMBER_SIZE,
    INVOICE_NUMBER_Y,
    INVOICE_TITLE_SIZE,
    INVOICE_TITLE_Y,
    ISSUE_LABEL_Y,
    ISSUE_VALUE_Y,
    ITEM_COUNT_SIZE,
    ITEMS_TITLE_Y,
    LABEL_SIZE,
    LEFT,
    LOGO_BOX,
    MUTED,
    NUMERIC_HEADER_SIZE,
    NUMERIC_SIZE,
    PAGE_HEIGHT,
    PAGE_WIDTH,
    PANEL_CORNER_RADIUS,
    PAYMENT_BOX,
    PAYMENT_COLUMN_1_LEFT,
    PAYMENT_COLUMN_2_LEFT,
    PAYMENT_HEADING_LEFT,
    PAYMENT_HEADING_SIZE,
    PAYMENT_LABEL_SIZE,
    PAYMENT_PANEL_RECT,
    PAYMENT_REFERENCE_RIGHT,
    PAYMENT_REFERENCE_SIZE,
    PAYMENT_TERMS_HEADING_Y,
    PAYMENT_VALUE_SIZE,
    PREVIEW_LABEL_SIZE,
    PREVIEW_LABEL_Y,
    QUANTITY_RIGHT,
    RATE_RIGHT,
    REFERENCE_ROW_COUNT,
    RIGHT,
    ROW_DESCRIPTION_LEADING,
    ROW_HEIGHT,
    ROW_SEPARATOR_GAP,
    ROW_SEPARATOR_OFFSET,
    SECTION_TITLE_SIZE,
    SUBTOTAL_LABEL_RIGHT,
    SUBTOTAL_LABEL_SIZE,
    SUBTOTAL_VALUE_RIGHT,
    SUBTOTAL_VALUE_SIZE,
    SUBTOTAL_Y,
    TABLE_HEADER,
    TABLE_HEADER_HEIGHT,
    TABLE_HEADER_TOP,
    TERMS_HEADING_SIZE,
    TERMS_TEXT_SIZE,
    TOP_RULE,
    TOTAL_BOX,
    TOTAL_BOX_RECT,
    TOTAL_LABEL_LEFT,
    TOTAL_LABEL_SIZE,
    TOTAL_VALUE_RIGHT,
    TOTAL_VALUE_SIZE,
    WORD_SPACING,
)
from .loader import resolve_project_path
from .models import BusinessConfig, InvoiceConfig

WINDOWS_RESERVED_FILENAMES = frozenset(
    {
        "CON",
        "PRN",
        "AUX",
        "NUL",
        *(f"COM{number}" for number in range(1, 10)),
        *(f"LPT{number}" for number in range(1, 10)),
    }
)


def render_invoice(
    business: BusinessConfig,
    invoice: InvoiceConfig,
    calculation: InvoiceCalculation,
    output_dir: str | Path = "output",
    *,
    prototype: bool = True,
) -> Path:
    """Render an invoice PDF using the approved point-based layout."""
    if len(calculation.line_items) != len(invoice.items):
        raise ValueError("Calculation line items must match the invoice line items.")

    register_lato_fonts()
    logo, logo_size = _load_logo(business.business.logo_path)
    destination = _reserve_destination(output_dir, invoice.invoice_number)

    try:
        canvas = Canvas(str(destination), pagesize=(PAGE_WIDTH, PAGE_HEIGHT))
        canvas.setTitle(f"Invoice {invoice.invoice_number}")
        canvas.setAuthor(business.business.name)
        _draw_first_page(
            canvas, business, invoice, calculation, logo, logo_size, prototype
        )
        canvas.save()
    except Exception:
        destination.unlink(missing_ok=True)
        raise
    return destination


def register_lato_fonts() -> None:
    """Register the OFL-licensed Lato faces installed by the font-lato dependency."""
    font_dir = files("font_lato").joinpath("files")
    font_files = {
        FONT_REGULAR: "Lato-Regular.ttf",
        # The distributed Lato package has no separate Semibold file; Bold is its closest face.
        FONT_SEMIBOLD: "Lato-Bold.ttf",
        FONT_BOLD: "Lato-Bold.ttf",
        FONT_BLACK: "Lato-Black.ttf",
    }
    registered = set(pdfmetrics.getRegisteredFontNames())
    for name, filename in font_files.items():
        if name not in registered:
            pdfmetrics.registerFont(TTFont(name, str(font_dir.joinpath(filename))))


def invoice_filename(invoice_number: str) -> str:
    """Return a portable, predictable PDF filename for an invoice number."""
    safe_number = re.sub(r"[^A-Za-z0-9._-]+", "-", invoice_number).strip(".-")
    if not safe_number:
        raise ValueError("Invoice number cannot produce an empty filename.")
    if safe_number.split(".", maxsplit=1)[0].upper() in WINDOWS_RESERVED_FILENAMES:
        raise ValueError("Invoice number cannot use a Windows-reserved filename.")
    return f"{safe_number}.pdf"


def format_currency(amount: Decimal, currency: str) -> str:
    """Format a Decimal monetary value consistently for the configured currency."""
    symbol = "R" if currency == "ZAR" else currency
    return f"{symbol} {round_money(amount):,.2f}"


def _reserve_destination(output_dir: str | Path, invoice_number: str) -> Path:
    directory = resolve_project_path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    destination = directory / invoice_filename(invoice_number)
    try:
        destination.touch(exist_ok=False)
    except FileExistsError as error:
        raise FileExistsError(f"Invoice PDF already exists: {destination}") from error
    return destination


def _draw_first_page(
    canvas: Canvas,
    business: BusinessConfig,
    invoice: InvoiceConfig,
    calculation: InvoiceCalculation,
    logo: ImageReader,
    logo_size: tuple[int, int],
    prototype: bool,
) -> None:
    _draw_header(canvas, business, invoice, logo, logo_size, prototype)
    _draw_customer_block(canvas, invoice)
    _draw_footer(canvas, business, prototype)

    rows = list(_expanded_rows(calculation.line_items))
    total_height = sum(row.height for row in rows)
    reference_height = REFERENCE_ROW_COUNT * ROW_HEIGHT
    note_lines = _wrap_notes(invoice.notes) if invoice.notes else ()
    rows_bottom = FIRST_ROW_TOP + total_height - ROW_SEPARATOR_GAP
    if (
        total_height <= reference_height
        and invoice.discount is None
        and _notes_fit(note_lines, rows_bottom)
    ):
        _draw_items_heading(canvas, invoice, TABLE_HEADER_TOP)
        _draw_rows(canvas, rows, FIRST_ROW_TOP, business.currency)
        _draw_reference_summary(canvas, business, invoice, calculation)
        _draw_notes(canvas, note_lines, rows_bottom)
        return

    remaining_rows = _draw_rows_that_fit(
        canvas,
        rows,
        FIRST_ROW_TOP,
        business.currency,
        TABLE_HEADER_TOP,
        max_separator_top=742.0,
        invoice=invoice,
    )
    _draw_summary_pages(
        canvas,
        business,
        invoice,
        calculation,
        logo,
        logo_size,
        remaining_rows,
        prototype,
    )


def _draw_summary_pages(
    canvas: Canvas,
    business: BusinessConfig,
    invoice: InvoiceConfig,
    calculation: InvoiceCalculation,
    logo: ImageReader,
    logo_size: tuple[int, int],
    rows: list[_ItemRow],
    prototype: bool,
) -> None:
    while rows:
        canvas.showPage()
        _draw_header(canvas, business, invoice, logo, logo_size, prototype)
        _draw_footer(canvas, business, prototype)
        rows = _draw_rows_that_fit(
            canvas,
            rows,
            CONTINUATION_TABLE_HEADER_TOP + TABLE_HEADER_HEIGHT,
            business.currency,
            CONTINUATION_TABLE_HEADER_TOP,
            max_separator_top=742.0,
            invoice=invoice,
            title_top=CONTINUATION_ITEMS_TITLE_Y,
        )

    canvas.showPage()
    _draw_header(canvas, business, invoice, logo, logo_size, prototype)
    _draw_footer(canvas, business, prototype)
    _draw_dynamic_summary(
        canvas, business, invoice, calculation, CONTINUATION_SUMMARY_TOP
    )


def _draw_rows_that_fit(
    canvas: Canvas,
    rows: list[_ItemRow],
    row_top: float,
    currency: str,
    table_header_top: float,
    max_separator_top: float,
    invoice: InvoiceConfig,
    title_top: float = ITEMS_TITLE_Y,
) -> list[_ItemRow]:
    _draw_items_heading(canvas, invoice, table_header_top, title_top)
    index = 0
    while (
        index < len(rows)
        and row_top + rows[index].height - ROW_SEPARATOR_GAP <= max_separator_top
    ):
        _draw_item_row(canvas, rows[index], row_top, currency)
        row_top += rows[index].height
        index += 1
    return rows[index:]


def _draw_header(
    canvas: Canvas,
    business: BusinessConfig,
    invoice: InvoiceConfig,
    logo: ImageReader,
    logo_size: tuple[int, int],
    prototype: bool,
) -> None:
    _rect_top(canvas, *TOP_RULE, fill=INK)
    _draw_logo(canvas, logo, logo_size)
    primary, descriptor = _wordmark_lines(business.business.name)
    _text(
        canvas,
        BRAND_LEFT,
        BRAND_NAME_Y,
        primary,
        FONT_BLACK,
        HEADER_NAME_SIZE,
        INK,
        word_spacing=WORD_SPACING,
    )
    _text(
        canvas,
        BRAND_LEFT,
        BRAND_DESCRIPTOR_Y,
        descriptor,
        FONT_BOLD,
        HEADER_DESCRIPTOR_SIZE,
        INK,
    )
    _text(
        canvas,
        BRAND_LEFT,
        BUSINESS_EMAIL_Y,
        business.business.email,
        FONT_REGULAR,
        HEADER_CONTACT_SIZE,
        MUTED,
    )
    _text(
        canvas,
        BRAND_LEFT,
        BUSINESS_WHATSAPP_Y,
        f"WhatsApp  {business.business.whatsapp}",
        FONT_REGULAR,
        HEADER_CONTACT_SIZE,
        MUTED,
    )
    _text(
        canvas,
        RIGHT,
        INVOICE_TITLE_Y,
        "INVOICE",
        FONT_BLACK,
        INVOICE_TITLE_SIZE,
        INK,
        right=True,
    )
    _text(
        canvas,
        RIGHT,
        INVOICE_NUMBER_Y,
        invoice.invoice_number,
        FONT_BOLD,
        INVOICE_NUMBER_SIZE,
        INK,
        right=True,
    )
    if prototype:
        _text(
            canvas,
            RIGHT,
            PREVIEW_LABEL_Y,
            "DESIGN PREVIEW  /  NOT ISSUED",
            FONT_BOLD,
            PREVIEW_LABEL_SIZE,
            MUTED,
            right=True,
        )
    _line_top(
        canvas, LEFT, HEADER_BOTTOM_RULE_Y, RIGHT, HEADER_BOTTOM_RULE_Y, HAIRLINE, 0.8
    )


def _draw_customer_block(canvas: Canvas, invoice: InvoiceConfig) -> None:
    _text(canvas, LEFT, BILL_TO_LABEL_Y, "B I L L  T O", FONT_BOLD, LABEL_SIZE, MUTED)
    _text(
        canvas,
        LEFT,
        CUSTOMER_NAME_Y,
        invoice.customer.name,
        FONT_BOLD,
        CUSTOMER_NAME_SIZE,
        INK,
        word_spacing=WORD_SPACING,
    )
    if invoice.customer.email:
        _text(
            canvas,
            LEFT,
            CUSTOMER_EMAIL_Y,
            invoice.customer.email,
            FONT_REGULAR,
            CUSTOMER_EMAIL_SIZE,
            MUTED,
        )
    if invoice.customer.phone:
        _text(
            canvas,
            LEFT,
            CUSTOMER_EXTRA_Y,
            invoice.customer.phone,
            FONT_REGULAR,
            CUSTOMER_EXTRA_SIZE,
            MUTED,
        )
    _line_top(
        canvas,
        CUSTOMER_SEPARATOR_X,
        CUSTOMER_SEPARATOR_TOP,
        CUSTOMER_SEPARATOR_X,
        CUSTOMER_SEPARATOR_BOTTOM,
        HAIRLINE,
        0.8,
    )
    _text(
        canvas,
        DATE_LEFT,
        ISSUE_LABEL_Y,
        "I S S U E  D A T E",
        FONT_BOLD,
        LABEL_SIZE,
        MUTED,
    )
    _text(
        canvas,
        DATE_LEFT,
        ISSUE_VALUE_Y,
        invoice.issue_date.strftime("%d %B %Y"),
        FONT_SEMIBOLD,
        INVOICE_NUMBER_SIZE,
        INK,
    )
    _text(
        canvas, DATE_LEFT, DUE_LABEL_Y, "D U E  D A T E", FONT_BOLD, LABEL_SIZE, MUTED
    )
    _text(
        canvas,
        DATE_LEFT,
        DUE_VALUE_Y,
        invoice.due_date.strftime("%d %B %Y"),
        FONT_SEMIBOLD,
        INVOICE_NUMBER_SIZE,
        INK,
    )


def _draw_items_heading(
    canvas: Canvas,
    invoice: InvoiceConfig,
    table_header_top: float,
    title_top: float = ITEMS_TITLE_Y,
) -> None:
    _text(
        canvas,
        LEFT,
        title_top,
        "S E R V I C E S  &  F E E S",
        FONT_BLACK,
        SECTION_TITLE_SIZE,
        INK,
    )
    _text(
        canvas,
        RIGHT,
        title_top,
        _line_item_count_label(len(invoice.items)),
        FONT_BOLD,
        ITEM_COUNT_SIZE,
        MUTED,
        right=True,
    )
    rule_y = table_header_top - 13.0
    _line_top(canvas, LEFT, rule_y, RIGHT, rule_y, INK, 1.1)
    _rect_top(
        canvas,
        LEFT,
        table_header_top,
        CONTENT_WIDTH,
        TABLE_HEADER_HEIGHT,
        fill=TABLE_HEADER,
    )
    _text(
        canvas,
        DESCRIPTION_LEFT,
        table_header_top + 18.0,
        "DESCRIPTION",
        FONT_BOLD,
        DESCRIPTION_HEADER_SIZE,
        MUTED,
    )
    _text(
        canvas,
        QUANTITY_RIGHT,
        table_header_top + 18.0,
        "QTY",
        FONT_BOLD,
        NUMERIC_HEADER_SIZE,
        MUTED,
        right=True,
    )
    _text(
        canvas,
        RATE_RIGHT,
        table_header_top + 18.0,
        "RATE",
        FONT_BOLD,
        NUMERIC_HEADER_SIZE,
        MUTED,
        right=True,
    )
    _text(
        canvas,
        AMOUNT_RIGHT,
        table_header_top + 18.0,
        "AMOUNT",
        FONT_BOLD,
        NUMERIC_HEADER_SIZE,
        MUTED,
        right=True,
    )


def _draw_rows(
    canvas: Canvas,
    rows: Iterable[_ItemRow],
    row_top: float,
    currency: str,
) -> float:
    for row in rows:
        _draw_item_row(canvas, row, row_top, currency)
        row_top += row.height
    return row_top


def _draw_item_row(
    canvas: Canvas, row: _ItemRow, row_top: float, currency: str
) -> None:
    for index, fragment in enumerate(row.fragments):
        _text(
            canvas,
            DESCRIPTION_LEFT,
            row_top + 18.0 + index * ROW_DESCRIPTION_LEADING,
            fragment,
            FONT_SEMIBOLD,
            DESCRIPTION_SIZE,
            INK,
            word_spacing=WORD_SPACING,
        )
    if row.show_amounts:
        _text(
            canvas,
            QUANTITY_RIGHT,
            row_top + 19.0,
            _format_quantity(row.line.item.quantity),
            FONT_REGULAR,
            NUMERIC_SIZE,
            INK,
            right=True,
        )
        _text(
            canvas,
            RATE_RIGHT,
            row_top + 19.0,
            format_currency(row.line.item.unit_price, currency),
            FONT_REGULAR,
            NUMERIC_SIZE,
            INK,
            right=True,
        )
        _text(
            canvas,
            AMOUNT_RIGHT,
            row_top + 19.0,
            format_currency(row.line.total, currency),
            FONT_SEMIBOLD,
            NUMERIC_SIZE,
            INK,
            right=True,
        )
    separator_y = (
        row_top
        + ROW_SEPARATOR_OFFSET
        + (len(row.fragments) - 1) * ROW_DESCRIPTION_LEADING
    )
    _line_top(canvas, LEFT, separator_y, RIGHT, separator_y, HAIRLINE, 0.7)


def _draw_reference_summary(
    canvas: Canvas,
    business: BusinessConfig,
    invoice: InvoiceConfig,
    calculation: InvoiceCalculation,
) -> None:
    _draw_totals(canvas, invoice, calculation, business.currency, SUBTOTAL_Y)
    _draw_payment_panel(canvas, business, invoice, PAYMENT_PANEL_RECT[1])
    _draw_payment_terms(canvas, business, invoice, PAYMENT_TERMS_HEADING_Y)


def _draw_dynamic_summary(
    canvas: Canvas,
    business: BusinessConfig,
    invoice: InvoiceConfig,
    calculation: InvoiceCalculation,
    top: float,
) -> None:
    subtotal_y = top
    _draw_totals(canvas, invoice, calculation, business.currency, subtotal_y)
    panel_top = subtotal_y + 102.89
    _draw_payment_panel(canvas, business, invoice, panel_top)
    _draw_payment_terms(canvas, business, invoice, panel_top + 161.01)
    _draw_notes(
        canvas, _wrap_notes(invoice.notes) if invoice.notes else (), panel_top + 189.0
    )


def _draw_totals(
    canvas: Canvas,
    invoice: InvoiceConfig,
    calculation: InvoiceCalculation,
    currency: str,
    subtotal_y: float,
) -> None:
    _text(
        canvas,
        SUBTOTAL_LABEL_RIGHT,
        subtotal_y,
        "Subtotal",
        FONT_REGULAR,
        SUBTOTAL_LABEL_SIZE,
        MUTED,
        right=True,
    )
    _text(
        canvas,
        SUBTOTAL_VALUE_RIGHT,
        subtotal_y,
        format_currency(calculation.subtotal, currency),
        FONT_SEMIBOLD,
        SUBTOTAL_VALUE_SIZE,
        INK,
        right=True,
    )
    total_box_top = subtotal_y + 18.0
    if invoice.discount is not None:
        label = "Discount"
        if invoice.discount.type == "percentage":
            label = f"Discount ({invoice.discount.amount:g}%)"
        _text(
            canvas,
            SUBTOTAL_LABEL_RIGHT,
            subtotal_y + 17.0,
            label,
            FONT_REGULAR,
            SUBTOTAL_LABEL_SIZE,
            MUTED,
            right=True,
        )
        _text(
            canvas,
            SUBTOTAL_VALUE_RIGHT,
            subtotal_y + 17.0,
            f"-{format_currency(calculation.discount_total, currency)}",
            FONT_SEMIBOLD,
            SUBTOTAL_VALUE_SIZE,
            INK,
            right=True,
        )
        total_box_top += 17.0

    total_left, _, total_width, total_height = TOTAL_BOX_RECT
    _rounded_rect_top(
        canvas,
        total_left,
        total_box_top,
        total_width,
        total_height,
        PANEL_CORNER_RADIUS,
        TOTAL_BOX,
    )
    _text(
        canvas,
        TOTAL_LABEL_LEFT,
        total_box_top + 23.0,
        "TOTAL DUE",
        FONT_BOLD,
        TOTAL_LABEL_SIZE,
        INK,
    )
    _text(
        canvas,
        TOTAL_VALUE_RIGHT,
        total_box_top + 47.0,
        format_currency(calculation.total_payable, currency),
        FONT_BLACK,
        TOTAL_VALUE_SIZE,
        INK,
        right=True,
    )


def _draw_payment_panel(
    canvas: Canvas,
    business: BusinessConfig,
    invoice: InvoiceConfig,
    top: float,
) -> None:
    _rounded_rect_top(
        canvas,
        LEFT,
        top,
        CONTENT_WIDTH,
        PAYMENT_PANEL_RECT[3],
        PANEL_CORNER_RADIUS,
        PAYMENT_BOX,
    )
    _text(
        canvas,
        PAYMENT_HEADING_LEFT,
        top + 27.01,
        "P A Y M E N T  D E T A I L S",
        FONT_BLACK,
        PAYMENT_HEADING_SIZE,
        INK,
    )
    _text(
        canvas,
        PAYMENT_REFERENCE_RIGHT,
        top + 27.01,
        f"Reference: {invoice.invoice_number}",
        FONT_SEMIBOLD,
        PAYMENT_REFERENCE_SIZE,
        INK,
        right=True,
    )
    _line_top(
        canvas,
        PAYMENT_HEADING_LEFT,
        top + 39.0,
        PAYMENT_REFERENCE_RIGHT,
        top + 39.0,
        HAIRLINE,
        0.8,
    )
    _payment_field(
        canvas,
        "BANK",
        business.banking.bank_name,
        PAYMENT_COLUMN_1_LEFT,
        top + 62.01,
        PAYMENT_VALUE_SIZE,
        word_spacing=True,
    )
    _payment_field(
        canvas,
        "ACCOUNT HOLDER",
        business.banking.account_holder,
        PAYMENT_COLUMN_2_LEFT,
        top + 62.01,
        ACCOUNT_HOLDER_SIZE,
        word_spacing=True,
    )
    _payment_field(
        canvas,
        "ACCOUNT NUMBER",
        business.banking.account_number,
        PAYMENT_COLUMN_1_LEFT,
        top + 105.01,
        PAYMENT_VALUE_SIZE,
    )
    _payment_field(
        canvas,
        "BRANCH CODE",
        business.banking.branch_code,
        PAYMENT_COLUMN_2_LEFT,
        top + 105.01,
        PAYMENT_VALUE_SIZE,
    )


def _payment_field(
    canvas: Canvas,
    label: str,
    value: str,
    left: float,
    label_top: float,
    size: float,
    *,
    word_spacing: bool = False,
) -> None:
    _text(canvas, left, label_top, label, FONT_BOLD, PAYMENT_LABEL_SIZE, MUTED)
    _text(
        canvas,
        left,
        label_top + 21.0,
        value,
        FONT_SEMIBOLD,
        size,
        INK,
        word_spacing=WORD_SPACING if word_spacing else 0.0,
    )


def _draw_payment_terms(
    canvas: Canvas,
    business: BusinessConfig,
    invoice: InvoiceConfig,
    heading_top: float,
) -> None:
    _text(
        canvas, LEFT, heading_top, "PAYMENT TERMS", FONT_BOLD, TERMS_HEADING_SIZE, MUTED
    )
    _text(
        canvas,
        LEFT,
        heading_top + 21.0,
        business.defaults.payment_terms,
        FONT_REGULAR,
        TERMS_TEXT_SIZE,
        INK,
        word_spacing=WORD_SPACING,
    )


def _draw_footer(canvas: Canvas, business: BusinessConfig, prototype: bool) -> None:
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
    if prototype:
        primary, _ = _wordmark_lines(business.business.name)
        _text(
            canvas,
            RIGHT,
            FOOTER_TEXT_Y,
            f"{primary}  /  {canvas.getPageNumber():02d}",
            FONT_BOLD,
            FOOTER_PAGE_SIZE,
            MUTED,
            right=True,
        )


def _draw_logo(canvas: Canvas, logo: ImageReader, size: tuple[int, int]) -> None:
    left, top, width, height = LOGO_BOX
    image_width, image_height = size
    scale = min(width / image_width, height / image_height)
    drawn_width = image_width * scale
    drawn_height = image_height * scale
    _image_top(
        canvas,
        logo,
        left + (width - drawn_width) / 2,
        top + (height - drawn_height) / 2,
        drawn_width,
        drawn_height,
    )


def _expanded_rows(lines: Iterable[CalculatedLineItem]) -> Iterable[_ItemRow]:
    for line in lines:
        fragments = _wrap_description(line.item.description)
        for start in range(0, len(fragments), 20):
            row_fragments = fragments[start : start + 20]
            yield _ItemRow(
                line=line,
                fragments=row_fragments,
                height=ROW_HEIGHT + (len(row_fragments) - 1) * ROW_DESCRIPTION_LEADING,
                show_amounts=start == 0,
            )


def _wrap_description(value: str) -> tuple[str, ...]:
    words = value.split()
    if not words:
        return ("",)
    maximum_width = DESCRIPTION_RIGHT - DESCRIPTION_LEFT
    lines: list[str] = []
    current = ""
    for word in words:
        if (
            _text_width(word, FONT_SEMIBOLD, DESCRIPTION_SIZE, WORD_SPACING)
            > maximum_width
        ):
            if current:
                lines.append(current)
                current = ""
            lines.extend(_split_long_word(word, maximum_width))
            continue
        candidate = word if not current else f"{current} {word}"
        if (
            current
            and _text_width(candidate, FONT_SEMIBOLD, DESCRIPTION_SIZE, WORD_SPACING)
            > maximum_width
        ):
            lines.append(current)
            current = word
        else:
            current = candidate
    if current:
        lines.append(current)
    return tuple(lines)


def _wrap_notes(value: str) -> tuple[str, ...]:
    """Wrap notes using their actual font metrics before assigning page space."""
    return _wrap_text(value, CONTENT_WIDTH, FONT_REGULAR, TERMS_TEXT_SIZE)


def _wrap_text(
    value: str, maximum_width: float, font: str, size: float
) -> tuple[str, ...]:
    words = value.split()
    if not words:
        return ()
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = word if not current else f"{current} {word}"
        if current and _text_width(candidate, font, size, WORD_SPACING) > maximum_width:
            lines.append(current)
            current = word
        else:
            current = candidate
    if current:
        lines.append(current)
    return tuple(lines)


def _notes_fit(lines: tuple[str, ...], rows_bottom: float) -> bool:
    if not lines:
        return True
    first_baseline = rows_bottom + 37.0
    last_baseline = first_baseline + (len(lines) - 1) * ROW_DESCRIPTION_LEADING
    return last_baseline <= SUBTOTAL_Y - ROW_SEPARATOR_GAP


def _draw_notes(canvas: Canvas, lines: tuple[str, ...], rows_bottom: float) -> None:
    if not lines:
        return
    heading_top = rows_bottom + 16.0
    _text(canvas, LEFT, heading_top, "NOTES", FONT_BOLD, TERMS_HEADING_SIZE, MUTED)
    for index, line in enumerate(lines):
        _text(
            canvas,
            LEFT,
            heading_top + 21.0 + index * ROW_DESCRIPTION_LEADING,
            line,
            FONT_REGULAR,
            TERMS_TEXT_SIZE,
            INK,
            word_spacing=WORD_SPACING,
        )


def _split_long_word(value: str, maximum_width: float) -> tuple[str, ...]:
    """Split an unbroken token so it remains inside the description column."""
    fragments: list[str] = []
    current = ""
    for character in value:
        candidate = f"{current}{character}"
        if (
            current
            and _text_width(candidate, FONT_SEMIBOLD, DESCRIPTION_SIZE, WORD_SPACING)
            > maximum_width
        ):
            fragments.append(current)
            current = character
        else:
            current = candidate
    if current:
        fragments.append(current)
    return tuple(fragments)


def _load_logo(path: str | Path) -> tuple[ImageReader, tuple[int, int]]:
    source = resolve_project_path(path)
    if not source.is_file():
        raise FileNotFoundError(f"Logo file not found: {source}")
    try:
        with Image.open(source) as source_image:
            image = source_image.convert("RGB")
    except (UnidentifiedImageError, OSError) as error:
        raise ValueError(f"Logo file is not a valid image: {source}") from error
    bounds = ImageChops.difference(
        image, Image.new("RGB", image.size, "white")
    ).getbbox()
    if bounds is None:
        raise ValueError(f"Logo image has no visible content: {source}")
    cropped = image.crop(bounds)
    return ImageReader(cropped), cropped.size


def _text(
    canvas: Canvas,
    x: float,
    baseline_top: float,
    value: str,
    font: str,
    size: float,
    color: str,
    *,
    right: bool = False,
    word_spacing: float = 0.0,
) -> None:
    canvas.setFillColor(HexColor(color))
    baseline = PAGE_HEIGHT - baseline_top
    if word_spacing == 0:
        canvas.setFont(font, size)
        draw = canvas.drawRightString if right else canvas.drawString
        draw(x, baseline, value)
        return

    origin_x = x - _text_width(value, font, size, word_spacing) if right else x
    text = canvas.beginText(origin_x, baseline)
    text.setFont(font, size)
    text.setFillColor(HexColor(color))
    text.setWordSpace(word_spacing)
    text.textOut(value)
    canvas.drawText(text)


def _text_width(value: str, font: str, size: float, word_spacing: float = 0.0) -> float:
    """Measure text exactly as the renderer draws it, including PDF word spacing."""
    return pdfmetrics.stringWidth(value, font, size) + value.count(" ") * word_spacing


def _line_top(
    canvas: Canvas,
    x1: float,
    y1: float,
    x2: float,
    y2: float,
    color: str,
    width: float,
) -> None:
    canvas.setStrokeColor(HexColor(color))
    canvas.setLineWidth(width)
    canvas.line(x1, PAGE_HEIGHT - y1, x2, PAGE_HEIGHT - y2)


def _rect_top(
    canvas: Canvas, left: float, top: float, width: float, height: float, *, fill: str
) -> None:
    canvas.setFillColor(HexColor(fill))
    canvas.rect(left, PAGE_HEIGHT - top - height, width, height, fill=1, stroke=0)


def _rounded_rect_top(
    canvas: Canvas,
    left: float,
    top: float,
    width: float,
    height: float,
    radius: float,
    fill: str,
) -> None:
    canvas.setFillColor(HexColor(fill))
    canvas.roundRect(
        left, PAGE_HEIGHT - top - height, width, height, radius, fill=1, stroke=0
    )


def _image_top(
    canvas: Canvas,
    image: ImageReader,
    left: float,
    top: float,
    width: float,
    height: float,
) -> None:
    canvas.drawImage(
        image, left, PAGE_HEIGHT - top - height, width, height, mask="auto"
    )


def _wordmark_lines(name: str) -> tuple[str, str]:
    words = name.upper().split()
    if len(words) > 2:
        primary = " ".join(words[:-2])
        descriptor = " ".join(" ".join(words[-2:]))
        return primary, descriptor
    return " ".join(words), ""


def _format_quantity(quantity: Decimal) -> str:
    rendered = f"{quantity:f}"
    return rendered.rstrip("0").rstrip(".") if "." in rendered else rendered


def _line_item_count_label(count: int) -> str:
    """Format the table count with grammatically correct singular wording."""
    return f"{count:02d} LINE ITEM" if count == 1 else f"{count:02d} LINE ITEMS"


class _ItemRow:
    def __init__(
        self,
        line: CalculatedLineItem,
        fragments: tuple[str, ...],
        height: float,
        show_amounts: bool,
    ) -> None:
        self.line = line
        self.fragments = fragments
        self.height = height
        self.show_amounts = show_amounts
