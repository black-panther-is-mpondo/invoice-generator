"""Shared calendar-date rules for newly created invoices."""

from datetime import date, timedelta


def due_date_for_issue_date(issue_date: date) -> date:
    """Return the payment due date two calendar days after an issue date."""
    return issue_date + timedelta(days=2)
