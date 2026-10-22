"""Normalize and validate extracted invoice fields."""
from __future__ import annotations

import re
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class InvoiceRecord(BaseModel):
    """Validated invoice record. Amounts are stored as decimal-like strings."""

    model_config = ConfigDict(str_strip_whitespace=True)

    supplier: str = Field(default="", max_length=250)
    invoice_number: str = Field(default="", max_length=120)
    invoice_date: str = Field(default="", max_length=30)
    currency: str = Field(default="", max_length=3)
    net_amount: str = Field(default="", max_length=40)
    tax_amount: str = Field(default="", max_length=40)
    total_amount: str = Field(default="", max_length=40)
    payable_amount: str = Field(default="", max_length=40)
    source_filename: str = Field(default="", max_length=255)
    extraction_notes: str = Field(default="", max_length=1000)

    @field_validator("currency")
    @classmethod
    def uppercase_currency(cls, value: str) -> str:
        return value.upper()

    @field_validator("invoice_date")
    @classmethod
    def normalize_date(cls, value: str) -> str:
        value = value.strip()
        if not value:
            return ""

        for fmt in (
            "%Y-%m-%d", "%d/%m/%Y", "%d.%m.%Y",
            "%d-%m-%Y", "%m/%d/%Y", "%d/%m/%y",
            "%d.%m.%y",
        ):
            try:
                return datetime.strptime(value, fmt).date().isoformat()
            except ValueError:
                pass

        return value

    @field_validator(
        "net_amount", "tax_amount", "total_amount", "payable_amount"
    )
    @classmethod
    def normalize_amount(cls, value: str) -> str:
        value = value.strip()
        if not value:
            return ""

        cleaned = re.sub(r"[^\d,.\-]", "", value)
        if not cleaned:
            return ""

        if "," in cleaned and "." in cleaned:
            if cleaned.rfind(",") > cleaned.rfind("."):
                # Greek format: 2.346,00
                cleaned = cleaned.replace(".", "").replace(",", ".")
            else:
                # English format: 2,346.00
                cleaned = cleaned.replace(",", "")

        elif "," in cleaned:
            tail = cleaned.rsplit(",", 1)[-1]
            if len(tail) in (1, 2):
                cleaned = cleaned.replace(",", ".")
            else:
                cleaned = cleaned.replace(",", "")

        elif "." in cleaned:
            tail = cleaned.rsplit(".", 1)[-1]
            if len(tail) > 2:
                cleaned = cleaned.replace(".", "")

        try:
            return format(
                Decimal(cleaned).quantize(Decimal("0.01")), "f"
            )
        except InvalidOperation:
            return value


def normalize_extracted(
    data: dict[str, Any], filename: str
) -> InvoiceRecord:
    """Build a validated record from best-effort extraction output."""
    allowed = set(InvoiceRecord.model_fields.keys())
    clean = {
        key: str(value or "")
        for key, value in data.items()
        if key in allowed
    }
    clean["source_filename"] = filename
    return InvoiceRecord.model_validate(clean)


def find_missing_fields(record: InvoiceRecord) -> list[str]:
    """Return fields requiring review."""
    required = (
        "supplier", "invoice_number", "invoice_date", "total_amount"
    )
    return [
        field for field in required
        if not getattr(record, field).strip()
    ]
