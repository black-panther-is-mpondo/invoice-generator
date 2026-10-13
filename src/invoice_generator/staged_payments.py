"""Validated, file-backed workflows for a deposit and final-balance invoice."""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator, model_validator

from .calculations import calculate_invoice, round_money
from .dates import due_date_for_issue_date
from .loader import (
    load_business_config,
    load_invoice_config,
    load_json,
    resolve_project_path,
)
from .models import (
    Customer,
    InvoiceConfig,
    InvoiceModel,
    LineItem,
    parse_decimal_string,
)
from .renderer import format_currency, render_invoice

StageStatus = Literal["not_invoiced", "unpaid", "paid"]


class DepositPayment(InvoiceModel):
    """A manually confirmed deposit payment; this does not process a transaction."""

    invoice_number: str = Field(min_length=1)
    amount_received: Decimal
    received_date: date
    payment_reference: str | None = None

    @field_validator("amount_received", mode="before")
    @classmethod
    def parse_amount_received(cls, value: object) -> Decimal:
        return parse_decimal_string(value)

    @model_validator(mode="after")
    def validate_amount_received(self) -> DepositPayment:
        if self.amount_received <= 0:
            raise ValueError("amount_received must be greater than zero")
        return self


class StagedProject(InvoiceModel):
    """Private state for a single project with one deposit and one final balance."""

    project_id: str = Field(min_length=1)
    customer_reference: str = Field(min_length=1)
    customer: Customer
    service_description: str = Field(min_length=1)
    project_total: Decimal
    deposit_percentage: Decimal
    deposit_invoice_number: str | None = None
    deposit_status: StageStatus = "not_invoiced"
    deposit_payment: DepositPayment | None = None
    final_invoice_number: str | None = None
    final_invoice_status: StageStatus = "not_invoiced"

    @field_validator("project_total", "deposit_percentage", mode="before")
    @classmethod
    def parse_decimal_fields(cls, value: object) -> Decimal:
        return parse_decimal_string(value)

    @model_validator(mode="after")
    def validate_stages(self) -> StagedProject:
        if self.project_total <= 0:
            raise ValueError("project_total must be greater than zero")
        if not Decimal("0") < self.deposit_percentage < Decimal("100"):
            raise ValueError(
                "deposit_percentage must be greater than 0 and less than 100"
            )
        if not self.customer.email:
            raise ValueError("customer.email is required for a staged project")

        if self.deposit_invoice_number is None:
            if (
                self.deposit_status != "not_invoiced"
                or self.deposit_payment is not None
            ):
                raise ValueError(
                    "A deposit without an invoice must be marked not_invoiced."
                )
        elif self.deposit_status == "not_invoiced":
            raise ValueError("An invoiced deposit cannot be marked not_invoiced.")
        elif self.deposit_status == "paid":
            if self.deposit_payment is None:
                raise ValueError("A paid deposit requires a confirmed payment record.")
            if self.deposit_payment.invoice_number != self.deposit_invoice_number:
                raise ValueError(
                    "The deposit payment must reference the deposit invoice."
                )
            if self.deposit_payment.amount_received != self.deposit_amount:
                raise ValueError(
                    "The deposit payment must equal the full deposit amount."
                )
        elif self.deposit_payment is not None:
            raise ValueError("An unpaid deposit cannot include a payment record.")

        if self.final_invoice_number is None:
            if self.final_invoice_status != "not_invoiced":
                raise ValueError(
                    "A final invoice without a number must be marked not_invoiced."
                )
        elif self.final_invoice_status == "not_invoiced":
            raise ValueError("A numbered final invoice cannot be marked not_invoiced.")
        elif self.final_invoice_number == self.deposit_invoice_number:
            raise ValueError(
                "The final invoice number must differ from the deposit invoice number."
            )
        return self

    @property
    def deposit_amount(self) -> Decimal:
        return round_money(
            self.project_total * self.deposit_percentage / Decimal("100")
        )

    @property
    def remaining_balance(self) -> Decimal:
        return round_money(self.project_total - self.deposit_amount)


def load_staged_project(path: str | Path) -> StagedProject:
    """Load and validate a private staged-project record."""
    return StagedProject.model_validate(load_json(path))


def save_staged_project(project: StagedProject, path: str | Path) -> Path:
    """Persist an updated staged-project record atomically."""
    destination = resolve_project_path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(f"{destination.suffix}.tmp")
    temporary.write_text(
        json.dumps(project.model_dump(mode="json"), indent=2) + "\n", encoding="utf-8"
    )
    temporary.replace(destination)
    return destination


def create_deposit_invoice(
    project_path: str | Path,
    invoice_path: str | Path,
    business_path: str | Path = "data/business.json",
    output_dir: str | Path = "output",
) -> Path:
    """Render the unpaid deposit invoice and then persist its invoice number."""
    project = load_staged_project(project_path)
    if project.deposit_invoice_number is not None:
        raise ValueError("A deposit invoice has already been created for this project.")

    business = load_business_config(business_path)
    template = load_invoice_config(invoice_path)
    invoice = _deposit_invoice(project, template, business.currency)
    destination = render_invoice(
        business, invoice, calculate_invoice(invoice), output_dir, prototype=False
    )
    save_staged_project(
        _updated_project(
            project,
            deposit_invoice_number=invoice.invoice_number,
            deposit_status="unpaid",
        ),
        project_path,
    )
    return destination


def record_deposit_payment(
    project_path: str | Path,
    invoice_number: str,
    amount_received: str,
    received_date: str | date,
    payment_reference: str | None = None,
) -> StagedProject:
    """Manually record a full confirmed deposit payment exactly once."""
    project = load_staged_project(project_path)
    if project.deposit_invoice_number is None:
        raise ValueError("Create the deposit invoice before recording a payment.")
    if project.deposit_status == "paid" or project.deposit_payment is not None:
        raise ValueError(
            "A deposit payment has already been recorded for this project."
        )
    if invoice_number != project.deposit_invoice_number:
        raise ValueError(
            "The payment invoice number does not match the deposit invoice."
        )

    payment = DepositPayment.model_validate(
        {
            "invoice_number": invoice_number,
            "amount_received": amount_received,
            "received_date": received_date,
            "payment_reference": payment_reference,
        }
    )
    if payment.amount_received != project.deposit_amount:
        raise ValueError(
            "The received amount must equal the full deposit before invoicing the balance."
        )

    updated = _updated_project(project, deposit_status="paid", deposit_payment=payment)
    save_staged_project(updated, project_path)
    return updated


def create_final_balance_invoice(
    project_path: str | Path,
    invoice_number: str,
    issue_date: str | date,
    business_path: str | Path = "data/business.json",
    output_dir: str | Path = "output",
) -> Path:
    """Render the final unpaid balance only after the deposit is fully confirmed."""
    project = load_staged_project(project_path)
    if project.deposit_status != "paid":
        raise ValueError(
            "Confirm the full deposit payment before creating the final-balance invoice."
        )
    if project.final_invoice_number is not None:
        raise ValueError(
            "A final-balance invoice has already been created for this project."
        )
    if invoice_number == project.deposit_invoice_number:
        raise ValueError(
            "The final invoice number must differ from the deposit invoice number."
        )

    business = load_business_config(business_path)
    invoice = _final_balance_invoice(
        project, invoice_number, issue_date, business.currency
    )
    destination = render_invoice(
        business, invoice, calculate_invoice(invoice), output_dir, prototype=False
    )
    save_staged_project(
        _updated_project(
            project,
            final_invoice_number=invoice.invoice_number,
            final_invoice_status="unpaid",
        ),
        project_path,
    )
    return destination


def _deposit_invoice(
    project: StagedProject, template: InvoiceConfig, currency: str
) -> InvoiceConfig:
    if (
        template.customer.name != project.customer.name
        or template.customer.email != project.customer.email
    ):
        raise ValueError(
            "The deposit invoice template customer must match the staged project."
        )
    return InvoiceConfig(
        invoice_number=template.invoice_number,
        issue_date=template.issue_date,
        due_date=due_date_for_issue_date(template.issue_date),
        customer=project.customer,
        items=[
            LineItem(
                description=(
                    f"{project.service_description} - upfront deposit "
                    f"({project.deposit_percentage:g}%)"
                ),
                quantity="1",
                unit_price=f"{project.deposit_amount:.2f}",
            )
        ],
        notes=(
            f"Full agreed project value: {format_currency(project.project_total, currency)}. "
            f"Upfront deposit: {project.deposit_percentage:g}% "
            f"({format_currency(project.deposit_amount, currency)}). "
            f"Remaining balance after the deposit: "
            f"{format_currency(project.remaining_balance, currency)}. "
            "The deposit is required before website design and development begins."
        ),
    )


def _final_balance_invoice(
    project: StagedProject,
    invoice_number: str,
    issue_date: str | date,
    currency: str,
) -> InvoiceConfig:
    assert project.deposit_invoice_number is not None
    return InvoiceConfig(
        invoice_number=invoice_number,
        issue_date=issue_date,
        customer=project.customer,
        items=[
            LineItem(
                description=f"{project.service_description} - final outstanding balance",
                quantity="1",
                unit_price=f"{project.remaining_balance:.2f}",
            )
        ],
        notes=(
            f"Full agreed project value: {format_currency(project.project_total, currency)}. "
            f"Deposit previously received: {format_currency(project.deposit_amount, currency)} "
            f"(deposit invoice {project.deposit_invoice_number}). "
            f"Remaining amount payable: {format_currency(project.remaining_balance, currency)}."
        ),
    )


def _updated_project(project: StagedProject, **changes: object) -> StagedProject:
    """Revalidate a persisted-state transition rather than mutating it in place."""
    return StagedProject.model_validate(project.model_dump(mode="json") | changes)
