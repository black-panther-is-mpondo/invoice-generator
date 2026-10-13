"""JSON loading helpers for invoice application entrypoints."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .models import BusinessConfig, InvoiceConfig

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def resolve_project_path(path: str | Path) -> Path:
    """Resolve relative application paths from the repository root."""
    candidate = Path(path)
    return candidate if candidate.is_absolute() else PROJECT_ROOT / candidate


def load_business_config(path: str | Path = "data/business.json") -> BusinessConfig:
    """Load and validate business configuration JSON."""
    return BusinessConfig.model_validate(load_json(path))


def load_invoice_config(path: str | Path = "data/invoice.json") -> InvoiceConfig:
    """Load and validate invoice configuration JSON."""
    return InvoiceConfig.model_validate(load_json(path))


def load_json(path: str | Path) -> dict[str, Any]:
    """Read a JSON object and report invalid configuration files clearly."""
    source = resolve_project_path(path)
    try:
        with source.open(encoding="utf-8") as file:
            data = json.load(file)
    except FileNotFoundError as error:
        raise FileNotFoundError(f"Configuration file not found: {source}") from error
    except json.JSONDecodeError as error:
        raise ValueError(f"Invalid JSON in configuration file: {source}") from error

    if not isinstance(data, dict):
        raise ValueError(f"Configuration file must contain a JSON object: {source}")
    return data
