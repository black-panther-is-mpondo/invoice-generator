# Invoice Generator

Invoice Generator creates professional A4 PDF invoices from validated JSON configuration. It keeps money calculations in Python `Decimal`, validates input with Pydantic, and renders PDFs with ReportLab using the approved numerical layout.

## Features

- Decimal-based line-item, discount, subtotal, and total calculations.
- JSON validation for business details, customer details, dates, and monetary values.
- Lato-based A4 PDF rendering with dynamic line-item pagination.
- No-overwrite protection for generated invoices.
- Jupyter notebooks for ordinary and two-stage invoice workflows.
- Sanitised example data and a neutral example logo for safe public use.

## Technology

- Python 3.12
- uv
- Pydantic
- ReportLab and Pillow
- Jupyter
- Black, Ruff, and pytest

## Install

Install Python 3.12, then install the locked project environment:

```powershell
uv sync
```

Run commands through `uv run`; it uses the project virtual environment automatically.

## Project Layout

```text
assets/       Private logo (ignored) and tracked example-logo.png
data/         Private runtime JSON (ignored) and tracked *.example.json
notebooks/    Invoice-generation notebook
output/       Generated PDFs (ignored, retained by .gitkeep)
references/   Public numerical invoice layout specification
src/          invoice_generator package
tests/        Automated tests
```

## Configuration

Tracked files under `data/` are fictional, validated examples:

```powershell
Copy-Item data/business.example.json data/business.json
Copy-Item data/invoice.example.json data/invoice.json
```

Replace the copied values with your own business, banking, customer, and invoice details. `quantity`, `unit_price`, and discount `amount` must be decimal strings, not JSON numbers. For a new invoice, omit `due_date`; it is calculated as two calendar days after `issue_date`. An explicit due date is retained for an existing issued invoice. The `discount` field may be `null`, a fixed amount, or a percentage:

```json
{"type": "percentage", "amount": "10"}
```

`data/business.json` and `data/invoice.json` are local private runtime files and are ignored by Git. Never add banking or customer details to an example file.

Set `business.logo_path` to your own local image. The tracked `assets/example-logo.png` is independent neutral artwork intended only for the public example. The renderer preserves a logo's aspect ratio within the approved logo box.

## Generate an Ordinary Invoice

Open `notebooks/create_invoice.ipynb` in VS Code or Jupyter, select the project Python kernel, and run all cells. The notebook loads the local private files by default and writes a PDF into `output/`; it never replaces an existing invoice file.

The same workflow is available from Python:

```python
from invoice_generator import generate_invoice, prepare_invoice

prepared = prepare_invoice()
pdf_path = generate_invoice(prepared)
```

For an isolated example run, pass the two tracked example JSON paths to `prepare_invoice` and a separate output directory to `generate_invoice`.

## Staged Payments

Use `notebooks/create_staged_invoices.ipynb` for a project with one upfront deposit and one final outstanding-balance invoice. Continue using `notebooks/create_invoice.ipynb` for ordinary invoices.

Create a private project record from the fictional `data/staged_project.example.json`, saving it under `data/staged_projects/`. Keep one record per project. The record stores the project value, deposit percentage, calculated amounts, invoice numbers, statuses, and any manually confirmed deposit payment.

The staged notebook has four configurable operations:

- `summary` validates the record and shows amounts without making changes.
- `create_deposit` creates one unpaid deposit invoice using the private invoice template.
- `record_deposit` persists a manually confirmed payment only when the configured invoice number and exact deposit amount match.
- `create_balance` creates one unpaid final-balance invoice only after the full deposit is recorded, with a due date two calendar days after its explicit issue date.

Generating a PDF never marks it paid or processes a bank transaction. Partial deposits are not treated as settled. The final operation requires an explicit new invoice number and issue date; its due date is automatically two calendar days later. It rejects duplicate numbers, duplicate stage invoices, and existing PDF paths. The final invoice includes the original deposit invoice reference and requests only the calculated remaining balance.

Private staged records, customer details, payment references, and temporary previews are ignored by Git. Do not put real project or payment data into the tracked example.

## Development

Format Python source and tests with Black:

```powershell
uv run black src tests
uv run black --check src tests
```

Lint with Ruff and run the full test suite:

```powershell
uv run ruff check .
uv run pytest
```

## Git Privacy

`.gitignore` excludes local JSON configuration, private staged-project records, the private logo, generated PDFs, Python environments, caches, notebook checkpoints, backup files, customer-information files, and local secrets. Generic examples, source code, tests, documentation, the layout specification, and `output/.gitkeep` remain eligible for tracking.

`.gitkeep` preserves the otherwise-empty `output/` directory when a clone is created. It is the only allowed tracked file in that directory.

Before committing, inspect the candidate file list and review new documentation, example data, assets, and notebook content for real business, banking, customer, machine-path, or generated-invoice information.

## Compliance

This project produces a general commercial invoice template. It does not calculate VAT or other taxes and is not a tax-invoice compliance system. Confirm local tax, accounting, retention, and invoice-content requirements with a qualified professional before using it for regulated or taxable transactions.
