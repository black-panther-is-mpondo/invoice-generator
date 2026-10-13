"""Pydantic models for business and invoice JSON input."""

from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


def parse_decimal_string(value: object) -> Decimal:
    """Accept only finite decimal strings so JSON money never becomes a float."""
    if not isinstance(value, str):
        raise ValueError("must be a decimal string")

    try:
        decimal_value = Decimal(value)
    except (InvalidOperation, ValueError) as error:
        raise ValueError("must be a valid decimal string") from error

    if not decimal_value.is_finite():
        raise ValueError("must be a finite decimal")
    return decimal_value


class InvoiceModel(BaseModel):
    """Base model that rejects unsupported fields, including VAT fields in version 1."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class BusinessDetails(InvoiceModel):
    name: str = Field(min_length=1)
    logo_path: str = Field(min_length=1)
    email: str = Field(min_length=1)
    whatsapp: str = Field(min_length=1)


class BankingDetails(InvoiceModel):
    bank_name: str = Field(min_length=1)
    account_holder: str = Field(min_length=1)
    account_number: str = Field(min_length=1)
    branch_code: str = Field(min_length=1)


class BusinessDefaults(InvoiceModel):
    payment_terms: str = Field(min_length=1)
    footer_message: str | None = None


class BusinessConfig(InvoiceModel):
    business: BusinessDetails
    currency: str = Field(min_length=3, max_length=3)
    banking: BankingDetails
    defaults: BusinessDefaults


class Customer(InvoiceModel):
    name: str = Field(min_length=1)
    email: str | None = None
    phone: str | None = None


class LineItem(InvoiceModel):
    description: str = Field(min_length=1)
    quantity: Decimal
    unit_price: Decimal

    @field_validator("quantity", "unit_price", mode="before")
    @classmethod
    def parse_decimal_fields(cls, value: object) -> Decimal:
        return parse_decimal_string(value)

    @model_validator(mode="after")
    def validate_amounts(self) -> Self:
        if self.quantity <= 0:
            raise ValueError("quantity must be greater than zero")
        if self.unit_price < 0:
            raise ValueError("unit_price must be non-negative")
        return self


class Discount(InvoiceModel):
    type: Literal["fixed", "percentage"]
    amount: Decimal

    @field_validator("amount", mode="before")
    @classmethod
    def parse_amount(cls, value: object) -> Decimal:
        return parse_decimal_string(value)

    @model_validator(mode="after")
    def validate_amount(self) -> Self:
        if self.amount < 0:
            raise ValueError("discount amount must be non-negative")
        if self.type == "percentage" and self.amount > 100:
            raise ValueError("percentage discount cannot exceed 100")
        return self


class InvoiceConfig(InvoiceModel):
    invoice_number: str = Field(min_length=1)
    issue_date: date
    due_date: date
    customer: Customer
    items: list[LineItem] = Field(min_length=1)
    discount: Discount | None = None
    notes: str | None = None

    @model_validator(mode="after")
    def validate_dates(self) -> Self:
        if self.due_date < self.issue_date:
            raise ValueError("due_date must be on or after issue_date")
        return self
