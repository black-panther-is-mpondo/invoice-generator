# Invoice Generator

## Project Overview

This repository is a Python-based A4 PDF invoice generator driven by JSON configuration. The package validates inputs with Pydantic, calculates monetary values with `Decimal`, and renders invoices through ReportLab.

The normal local workflow is:

1. Maintain private `data/business.json` and `data/invoice.json`.
2. Use `notebooks/create_invoice.ipynb` for ordinary invoices, or maintain a private staged-project record and use `notebooks/create_staged_invoices.ipynb` for one deposit plus one final balance.
3. Run all notebook cells.
4. Find the generated PDF in `output/`.

Keep reusable business logic in `src/invoice_generator/`; the notebook should only coordinate the package.

## Environment

- Python 3.12
- Windows and PowerShell
- uv for dependencies and virtual environments
- Jupyter for the notebook workflow
- ReportLab for PDFs
- Pydantic for validation
- `Decimal` for money
- Black for formatting
- Ruff for linting
- pytest for tests

Use `uv sync` to install dependencies. Before completing Python changes, run:

```powershell
uv run black src tests
uv run black --check src tests
uv run ruff check .
uv run pytest
```

## Repository Structure

- `assets/`: Local private logo (ignored) and the tracked neutral example logo.
- `data/`: Ignored private runtime configuration and staged-project records, plus tracked fictional examples.
- `notebooks/`: User-facing ordinary and staged-invoice orchestration notebooks.
- `output/`: Ignored generated invoices; `output/.gitkeep` preserves the directory.
- `references/invoice_layout_spec.json`: Authoritative public numerical layout specification.
- `src/invoice_generator/`: Application package.
- `tests/`: Automated validation, calculation, rendering, and notebook tests.

Resolve application-relative paths from the repository root, not the terminal working directory.

## Data and Privacy

`data/business.json`, `data/invoice.json`, `data/staged_projects/`, and `assets/logo.png` are private local files. Do not modify, delete, rename, print, or commit them without explicit user approval. They may contain business, banking, customer, payment, and branding information.

Use `data/business.example.json`, `data/invoice.example.json`, `data/staged_project.example.json`, and `assets/example-logo.png` for public examples and tests. Keep all example business, customer, contact, banking, payment, and invoice values fictional.

Do not hardcode banking or customer information. Do not commit generated PDFs, virtual environments, caches, notebook outputs, private backups, customer-information files, environment files, or secrets. Audit public filenames and content before Git operations.

## Invoice Contract

An invoice includes an invoice number, issue date, customer data, line items, an optional discount, and optional notes. Monetary input values are decimal strings in JSON. New invoices calculate `due_date` as two calendar days after `issue_date` when it is omitted; explicit due dates are preserved for issued invoices. The discount may be `null`, fixed, or percentage-based.

Calculate money with `Decimal`; do not use binary floating point. Do not require calculated totals in input JSON. Preserve no-overwrite output behavior.

## Staged Payments

Support one deposit and one final-balance invoice through `src/invoice_generator/staged_payments.py`. Use the existing invoice renderer and models; do not duplicate PDF layout or ordinary calculation code. A generated deposit invoice is unpaid until a user explicitly records a full confirmed payment in the private project record. Partial payments do not unlock final-balance creation. Require a new invoice number and explicit issue date for the final balance; calculate its due date two calendar days later.

## Layout Requirements

`references/invoice_layout_spec.json` is the source of truth for the approved invoice design. Preserve every numerical layout value, including dimensions, margins, positions, typography, logo scaling, word spacing, colours, table geometry, totals, payment section, and footer placement.

Use Lato through the existing dependency and retain dynamic content positioning for longer or multi-page invoices. Do not independently redesign the PDF or change financial calculation logic while making layout-related changes.

## Development Standards

Inspect relevant files before editing. Make the smallest correct change. Use type hints and clear errors. Do not introduce unnecessary frameworks or services.

Test valid and invalid JSON, required fields, date validation, quantities and prices, decimal precision, discounts, totals, PDF generation, and multi-page rendering when affected. Do not add a software licence without explicit approval.
