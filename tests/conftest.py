from __future__ import annotations

import pytest


@pytest.fixture
def valid_business_data() -> dict[str, object]:
    return {
        "business": {
            "name": "Example Digital Studio",
            "logo_path": "assets/example-logo.png",
            "whatsapp": "0712345678",
            "email": "hello@example.com",
        },
        "currency": "ZAR",
        "banking": {
            "account_holder": "Example Holder",
            "bank_name": "Example Bank",
            "account_number": "0000000000",
            "branch_code": "000000",
        },
        "defaults": {"payment_terms": "Pay by the due date."},
    }


@pytest.fixture
def valid_invoice_data() -> dict[str, object]:
    return {
        "invoice_number": "INV-001",
        "issue_date": "2026-10-13",
        "due_date": "2026-10-27",
        "customer": {
            "name": "Example Client",
            "email": "client@example.com",
            "phone": "",
        },
        "items": [
            {
                "description": "Website design",
                "quantity": "1",
                "unit_price": "100.00",
            }
        ],
        "discount": None,
        "notes": "",
    }
