"""CSV and Excel exports for InvoicePilot."""
from __future__ import annotations

from io import BytesIO, StringIO
from typing import Any

import pandas as pd


def to_csv(rows: list[dict[str, Any]]) -> bytes:
    """Return UTF-8-with-BOM CSV bytes for compatibility with Excel."""
    buffer = StringIO()
    pd.DataFrame(rows).to_csv(buffer, index=False)
    return buffer.getvalue().encode("utf-8-sig")


def to_excel(rows: list[dict[str, Any]]) -> bytes:
    """Return an Excel workbook as bytes."""
    buffer = BytesIO()

    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        pd.DataFrame(rows).to_excel(
            writer,
            index=False,
            sheet_name="Invoices",
        )

    return buffer.getvalue()
