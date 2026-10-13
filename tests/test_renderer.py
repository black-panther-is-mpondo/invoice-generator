from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest
from pypdf import PdfReader
from reportlab.pdfbase import pdfmetrics

import invoice_generator.renderer as renderer_module
from invoice_generator.calculations import calculate_invoice
from invoice_generator.layout import (
    CONTENT_WIDTH,
    CUSTOMER_EMAIL_Y,
    DESCRIPTION_LEFT,
    DESCRIPTION_RIGHT,
    DESCRIPTION_SIZE,
    INVOICE_TITLE_SIZE,
    LEFT,
    LOGO_BOX,
    PAGE_HEIGHT,
    PAGE_WIDTH,
    RIGHT,
    TERMS_TEXT_SIZE,
    TOTAL_VALUE_SIZE,
    TYPOGRAPHY_SCALE,
    WORD_SPACING,
)
from invoice_generator.models import BusinessConfig, InvoiceConfig
from invoice_generator.renderer import (
    _text_width,
    _wrap_description,
    _wrap_notes,
    invoice_filename,
    register_lato_fonts,
    render_invoice,
)


def _render(
    business_data: dict[str, object],
    invoice_data: dict[str, object],
    output_dir: Path,
) -> Path:
    business = BusinessConfig.model_validate(business_data)
    invoice = InvoiceConfig.model_validate(invoice_data)
    return render_invoice(business, invoice, calculate_invoice(invoice), output_dir)


def _pdf_text(path: Path) -> str:
    return "\n".join(page.extract_text() for page in PdfReader(path).pages)


def test_generates_pdf_with_invoice_customer_and_totals(
    valid_business_data: dict[str, object],
    valid_invoice_data: dict[str, object],
    tmp_path: Path,
) -> None:
    output = _render(valid_business_data, valid_invoice_data, tmp_path)
    text = _pdf_text(output)

    assert output.name == "INV-001.pdf"
    assert output.is_file()
    assert "INV-001" in text
    assert "Example Client" in text
    assert "R 100.00" in text


def test_renders_optional_discount(
    valid_business_data: dict[str, object],
    valid_invoice_data: dict[str, object],
    tmp_path: Path,
) -> None:
    valid_invoice_data["discount"] = {"type": "percentage", "amount": "10"}

    output = _render(valid_business_data, valid_invoice_data, tmp_path)
    text = _pdf_text(output)

    assert "Discount (10%)" in text
    assert "R 90.00" in text


def test_rejects_missing_logo(
    valid_business_data: dict[str, object],
    valid_invoice_data: dict[str, object],
    tmp_path: Path,
) -> None:
    business_data = valid_business_data.copy()
    business_data["business"] = {
        **business_data["business"],
        "logo_path": "assets/missing.png",
    }

    with pytest.raises(FileNotFoundError, match="Logo file not found"):
        _render(business_data, valid_invoice_data, tmp_path)

    assert not list(tmp_path.iterdir())


def test_rejects_invalid_logo(
    valid_business_data: dict[str, object],
    valid_invoice_data: dict[str, object],
    tmp_path: Path,
) -> None:
    invalid_logo = tmp_path / "not-an-image.png"
    invalid_logo.write_bytes(b"not an image")
    business_data = valid_business_data.copy()
    business_data["business"] = {
        **business_data["business"],
        "logo_path": str(invalid_logo),
    }

    with pytest.raises(ValueError, match="not a valid image"):
        _render(business_data, valid_invoice_data, tmp_path)

    assert invalid_logo.is_file()
    assert list(tmp_path.iterdir()) == [invalid_logo]


def test_supports_multiple_pages(
    valid_business_data: dict[str, object],
    valid_invoice_data: dict[str, object],
    tmp_path: Path,
) -> None:
    valid_invoice_data["items"] = [
        {
            "description": f"Service item {number}",
            "quantity": "1",
            "unit_price": "10.00",
        }
        for number in range(1, 46)
    ]

    output = _render(valid_business_data, valid_invoice_data, tmp_path)
    reader = PdfReader(output)

    assert len(reader.pages) >= 2
    assert "Service item 45" in "\n".join(page.extract_text() for page in reader.pages)


@pytest.mark.parametrize("item_count", [1, 2, 10, 25, 50])
def test_renders_expected_totals_for_varied_item_counts(
    valid_business_data: dict[str, object],
    valid_invoice_data: dict[str, object],
    tmp_path: Path,
    item_count: int,
) -> None:
    valid_invoice_data["invoice_number"] = f"INV-COUNT-{item_count}"
    valid_invoice_data["items"] = [
        {"description": f"QA item {number}", "quantity": "1", "unit_price": "0.10"}
        for number in range(1, item_count + 1)
    ]

    output = _render(valid_business_data, valid_invoice_data, tmp_path)
    reader = PdfReader(output)
    text = "\n".join(page.extract_text() for page in reader.pages)

    assert output.read_bytes().startswith(b"%PDF")
    assert f"QA item {item_count}" in text
    assert f"R {Decimal(item_count) / Decimal('10'):.2f}" in text
    if item_count >= 10:
        assert len(reader.pages) >= 2


def test_supports_long_descriptions(
    valid_business_data: dict[str, object],
    valid_invoice_data: dict[str, object],
    tmp_path: Path,
) -> None:
    valid_invoice_data["items"] = [
        {
            "description": "Extended design requirement " * 80,
            "quantity": "1",
            "unit_price": "100.00",
        }
    ]

    output = _render(valid_business_data, valid_invoice_data, tmp_path)

    assert "Extended design requirement" in _pdf_text(output)


def test_short_invoice_notes_fit_once_on_the_reference_page(
    valid_business_data: dict[str, object],
    valid_invoice_data: dict[str, object],
    tmp_path: Path,
) -> None:
    valid_invoice_data["notes"] = (
        "Full agreed project value: R 3,500.00. Upfront deposit: 50% (R 1,750.00). "
        "Remaining balance after the deposit: R 1,750.00."
    )
    output = _render(valid_business_data, valid_invoice_data, tmp_path)
    reader = PdfReader(output)
    text = " ".join(_pdf_text(output).split())

    assert len(reader.pages) == 1
    assert text.count("NOTES") == 1
    assert "Full agreed project value" in text
    assert "TOTAL DUE" in text
    assert all(
        _text_width(line, "Lato-Regular", TERMS_TEXT_SIZE, WORD_SPACING)
        <= CONTENT_WIDTH
        for line in _wrap_notes(valid_invoice_data["notes"])
    )


def test_rejects_existing_output_file(
    valid_business_data: dict[str, object],
    valid_invoice_data: dict[str, object],
    tmp_path: Path,
) -> None:
    _render(valid_business_data, valid_invoice_data, tmp_path)

    with pytest.raises(FileExistsError, match="already exists"):
        _render(valid_business_data, valid_invoice_data, tmp_path)


def test_invoice_filename_sanitises_path_characters() -> None:
    assert invoice_filename("INV / 001") == "INV-001.pdf"


@pytest.mark.parametrize("invoice_number", ["CON", "aux.txt", "LPT1", "COM9.pdf"])
def test_invoice_filename_rejects_windows_reserved_names(invoice_number: str) -> None:
    with pytest.raises(ValueError, match="Windows-reserved"):
        invoice_filename(invoice_number)


def test_long_unbroken_description_is_wrapped_within_its_column(
    valid_business_data: dict[str, object],
    valid_invoice_data: dict[str, object],
    tmp_path: Path,
) -> None:
    register_lato_fonts()
    description = "A" * 1_000
    fragments = _wrap_description(description)

    assert len(fragments) > 1
    assert all(
        _text_width(fragment, "Lato-Semibold", DESCRIPTION_SIZE, WORD_SPACING)
        <= DESCRIPTION_RIGHT - DESCRIPTION_LEFT
        for fragment in fragments
    )

    valid_invoice_data["items"] = [
        {"description": description, "quantity": "1", "unit_price": "100.00"}
    ]
    output = _render(valid_business_data, valid_invoice_data, tmp_path)

    assert fragments[0] in _pdf_text(output)
    assert fragments[-1] in _pdf_text(output)


def test_failed_render_removes_its_reserved_destination(
    valid_business_data: dict[str, object],
    valid_invoice_data: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    def fail_render(*args: object, **kwargs: object) -> None:
        raise RuntimeError("intentional render failure")

    monkeypatch.setattr(renderer_module, "_draw_first_page", fail_render)

    with pytest.raises(RuntimeError, match="intentional render failure"):
        _render(valid_business_data, valid_invoice_data, tmp_path)

    assert not (tmp_path / "INV-001.pdf").exists()


def test_uses_specified_page_geometry_and_lato_fonts(
    valid_business_data: dict[str, object],
    valid_invoice_data: dict[str, object],
    tmp_path: Path,
) -> None:
    valid_invoice_data["items"].append(
        {"description": "Maintenance", "quantity": "2", "unit_price": "50.00"}
    )
    output = _render(valid_business_data, valid_invoice_data, tmp_path)
    page = PdfReader(output).pages[0]

    assert float(page.mediabox.width) == pytest.approx(PAGE_WIDTH)
    assert float(page.mediabox.height) == pytest.approx(PAGE_HEIGHT)
    assert RIGHT - LEFT == CONTENT_WIDTH
    register_lato_fonts()
    assert {"Lato-Regular", "Lato-Semibold", "Lato-Bold", "Lato-Black"} <= set(
        pdfmetrics.getRegisteredFontNames()
    )


def test_refinement_constants_match_the_specification() -> None:
    specification_path = (
        Path(__file__).resolve().parents[1] / "references" / "invoice_layout_spec.json"
    )
    specification = json.loads(specification_path.read_text(encoding="utf-8"))

    assert TYPOGRAPHY_SCALE == pytest.approx(0.92)
    assert INVOICE_TITLE_SIZE == pytest.approx(29.44)
    assert TOTAL_VALUE_SIZE == pytest.approx(17.85)
    assert DESCRIPTION_SIZE == pytest.approx(9.66)
    assert LOGO_BOX[2:] == pytest.approx((61.6, 52.096))
    assert CUSTOMER_EMAIL_Y == pytest.approx(256.0)
    assert specification["refinement_a"]["word_spacing_pt"] == WORD_SPACING
    assert specification["elements"]["header"]["title"]["size_pt"] == INVOICE_TITLE_SIZE
    assert (
        specification["elements"]["totals"]["total_value"]["size_pt"]
        == TOTAL_VALUE_SIZE
    )


def test_word_spacing_uses_pdf_metrics_and_text_operations(
    valid_business_data: dict[str, object],
    valid_invoice_data: dict[str, object],
    tmp_path: Path,
) -> None:
    register_lato_fonts()
    base_width = pdfmetrics.stringWidth("Example Client", "Lato-Bold", 17.48)

    assert _text_width(
        "Example Client", "Lato-Bold", 17.48, WORD_SPACING
    ) == pytest.approx(base_width + WORD_SPACING)
    output = _render(valid_business_data, valid_invoice_data, tmp_path)
    content = PdfReader(output).pages[0].get_contents().get_data()
    assert b".5 Tw" in content
