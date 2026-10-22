"""SQLite persistence layer for invoice records."""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from invoicepilot.processing import InvoiceRecord


FIELDS = [
    "supplier",
    "invoice_number",
    "invoice_date",
    "currency",
    "net_amount",
    "tax_amount",
    "total_amount",
    "payable_amount",
    "source_filename",
    "extraction_notes",
]


class InvoiceDatabase:
    def __init__(
        self,
        db_path: str | Path = "data/invoicepilot.db",
    ):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(
            str(self.db_path),
            timeout=30,
        )
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 30000")
        return conn

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        """Commit or roll back the transaction, then always close."""
        conn = self._connect()
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def _initialize(self) -> None:
        with self._connection() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS invoices (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    supplier TEXT NOT NULL DEFAULT '',
                    invoice_number TEXT NOT NULL DEFAULT '',
                    invoice_date TEXT NOT NULL DEFAULT '',
                    currency TEXT NOT NULL DEFAULT '',
                    net_amount TEXT NOT NULL DEFAULT '',
                    tax_amount TEXT NOT NULL DEFAULT '',
                    total_amount TEXT NOT NULL DEFAULT '',
                    payable_amount TEXT NOT NULL DEFAULT '',
                    source_filename TEXT NOT NULL DEFAULT '',
                    extraction_notes TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
            """)

            columns = {
                row["name"]
                for row in conn.execute(
                    "PRAGMA table_info(invoices)"
                ).fetchall()
            }

            migrations = {
                "supplier": "TEXT NOT NULL DEFAULT ''",
                "invoice_number": "TEXT NOT NULL DEFAULT ''",
                "invoice_date": "TEXT NOT NULL DEFAULT ''",
                "currency": "TEXT NOT NULL DEFAULT ''",
                "net_amount": "TEXT NOT NULL DEFAULT ''",
                "tax_amount": "TEXT NOT NULL DEFAULT ''",
                "total_amount": "TEXT NOT NULL DEFAULT ''",
                "payable_amount": "TEXT NOT NULL DEFAULT ''",
                "source_filename": "TEXT NOT NULL DEFAULT ''",
                "extraction_notes": "TEXT NOT NULL DEFAULT ''",
                "created_at": "TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP",
                "updated_at": "TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP",
            }

            for column, definition in migrations.items():
                if column not in columns:
                    conn.execute(
                        f"ALTER TABLE invoices "
                        f"ADD COLUMN {column} {definition}"
                    )

            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_invoice_number
                ON invoices(invoice_number)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_supplier
                ON invoices(supplier)
            """)

    def add(self, record: InvoiceRecord) -> int:
        values = record.model_dump()
        placeholders = ", ".join("?" for _ in FIELDS)

        with self._connection() as conn:
            cursor = conn.execute(
                f"INSERT INTO invoices ({', '.join(FIELDS)}) "
                f"VALUES ({placeholders})",
                [values[field] for field in FIELDS],
            )
            invoice_id = cursor.lastrowid

            if invoice_id is None:
                raise RuntimeError(
                    "The database did not return an invoice ID."
                )

            return int(invoice_id)

    def list_all(self, search: str = "") -> list[dict[str, Any]]:
        with self._connection() as conn:
            if search.strip():
                term = f"%{search.strip()}%"
                rows = conn.execute("""
                    SELECT * FROM invoices
                    WHERE supplier LIKE ?
                       OR invoice_number LIKE ?
                       OR source_filename LIKE ?
                    ORDER BY created_at DESC, id DESC
                """, (term, term, term)).fetchall()
            else:
                rows = conn.execute("""
                    SELECT * FROM invoices
                    ORDER BY created_at DESC, id DESC
                """).fetchall()

        return [dict(row) for row in rows]

    def update(self, invoice_id: int, record: InvoiceRecord) -> None:
        values = record.model_dump()
        assignments = ", ".join(f"{field} = ?" for field in FIELDS)

        with self._connection() as conn:
            cursor = conn.execute(
                f"UPDATE invoices SET {assignments}, "
                "updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                [values[field] for field in FIELDS] + [invoice_id],
            )

            if cursor.rowcount == 0:
                raise ValueError(
                    f"Invoice record {invoice_id} was not found."
                )

    def delete(self, invoice_id: int) -> None:
        with self._connection() as conn:
            cursor = conn.execute(
                "DELETE FROM invoices WHERE id = ?",
                (invoice_id,),
            )

            if cursor.rowcount == 0:
                raise ValueError(
                    f"Invoice record {invoice_id} was not found."
                )

    def possible_duplicates(self) -> list[tuple[int, int, str]]:
        """Find pairs sharing a non-empty supplier and invoice number."""
        with self._connection() as conn:
            rows = conn.execute("""
                SELECT a.id AS first_id,
                       b.id AS second_id,
                       a.invoice_number AS invoice_number
                FROM invoices a
                JOIN invoices b
                  ON a.id < b.id
                 AND LOWER(TRIM(a.invoice_number)) =
                     LOWER(TRIM(b.invoice_number))
                 AND LOWER(TRIM(a.supplier)) =
                     LOWER(TRIM(b.supplier))
                WHERE TRIM(a.invoice_number) <> ''
            """).fetchall()

        return [
            (
                row["first_id"],
                row["second_id"],
                row["invoice_number"],
            )
            for row in rows
        ]
