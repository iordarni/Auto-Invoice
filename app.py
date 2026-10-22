"""InvoicePilot Streamlit application."""
from __future__ import annotations

import hashlib
import json
import os

import pandas as pd
import streamlit as st

from invoicepilot.database import InvoiceDatabase
from invoicepilot.exports import to_csv, to_excel
from invoicepilot.extraction import (
    extract_text,
    parse_invoice_text,
    SUPPORTED_EXTENSIONS,
)
from invoicepilot.processing import (
    InvoiceRecord,
    find_missing_fields,
    normalize_extracted,
)


st.set_page_config(
    page_title="InvoicePilot",
    page_icon="🧾",
    layout="wide",
)

DB_PATH = os.getenv("INVOICEPILOT_DB", "data/invoicepilot.db")
db = InvoiceDatabase(DB_PATH)

st.title("🧾 InvoicePilot")
st.caption(
    "Extract, review, organize, and export invoice data. "
    "Supports English and Greek invoices using best-effort extraction. "
    "Always verify extracted values before accounting or tax filings."
)


with st.sidebar:
    st.header("Settings")

    use_ocr = st.checkbox(
        "Enable OCR for scanned documents",
        value=True,
    )

    st.caption(
        "OCR requires Tesseract. For Greek scanned invoices, "
        "install the Greek 'ell' language data. Digital PDFs with "
        "selectable text do not require OCR."
    )

    st.divider()
    st.markdown("**Privacy note**")
    st.caption(
        "In local mode, files and the database stay on this computer. "
        "Uploaded files are processed in memory and are not saved by the app."
    )


tab_upload, tab_records, tab_duplicates, tab_help = st.tabs(
    [
        "Upload invoices",
        "Saved invoices",
        "Duplicate check",
        "Help & setup",
    ]
)


# UPLOAD INVOICES
with tab_upload:
    st.subheader("Upload one or more documents")

    uploads = st.file_uploader(
        "Choose PDF or image files",
        type=[ext.lstrip(".") for ext in sorted(SUPPORTED_EXTENSIONS)],
        accept_multiple_files=True,
        help="Supported: PDF, PNG, JPG/JPEG, TIFF, BMP",
    )

    if uploads:
        for upload in uploads:
            with st.expander(
                f"Review: {upload.name}",
                expanded=True,
            ):
                try:
                    raw_text, processing_notes = extract_text(
                        upload.getvalue(),
                        upload.name,
                        use_ocr=use_ocr,
                    )

                    parsed = parse_invoice_text(raw_text)
                    record = normalize_extracted(parsed, upload.name)
                    missing = find_missing_fields(record)

                    if missing:
                        st.warning(
                            "Please review missing fields: "
                            + ", ".join(missing)
                        )

                    st.caption(processing_notes)

                    if raw_text:
                        with st.popover("View extracted source text"):
                            st.text(raw_text[:12000])
                    else:
                        st.warning(
                            "No readable text was extracted. Check the PDF "
                            "or OCR setup, or enter invoice details manually."
                        )

                    form_key = (
                        f"save_{upload.name}_{upload.size}_"
                        f"{hashlib.sha256(upload.getvalue()).hexdigest()[:12]}"
                    )

                    with st.form(form_key):
                        c1, c2 = st.columns(2)

                        with c1:
                            supplier = st.text_input(
                                "Supplier",
                                value=record.supplier,
                            )
                            invoice_number = st.text_input(
                                "Invoice number",
                                value=record.invoice_number,
                            )
                            invoice_date = st.text_input(
                                "Invoice date (YYYY-MM-DD recommended)",
                                value=record.invoice_date,
                            )
                            currency = st.text_input(
                                "Currency (e.g. EUR)",
                                value=record.currency,
                                max_chars=3,
                            )

                        with c2:
                            net_amount = st.text_input(
                                "Net amount",
                                value=record.net_amount,
                            )
                            tax_amount = st.text_input(
                                "Tax amount / VAT",
                                value=record.tax_amount,
                            )
                            total_amount = st.text_input(
                                "Total amount (gross)",
                                value=record.total_amount,
                            )
                            payable_amount = st.text_input(
                                "Payable amount",
                                value=record.payable_amount,
                            )
                            st.text_input(
                                "Source file",
                                value=upload.name,
                                disabled=True,
                            )

                        extraction_notes = st.text_input(
                            "Notes",
                            value=record.extraction_notes,
                        )

                        submitted = st.form_submit_button(
                            "Save invoice",
                            type="primary",
                        )

                    if submitted:
                        try:
                            reviewed = InvoiceRecord(
                                supplier=supplier,
                                invoice_number=invoice_number,
                                invoice_date=invoice_date,
                                currency=currency,
                                net_amount=net_amount,
                                tax_amount=tax_amount,
                                total_amount=total_amount,
                                payable_amount=payable_amount,
                                source_filename=upload.name,
                                extraction_notes=extraction_notes,
                            )

                            fingerprint_payload = json.dumps(
                                reviewed.model_dump(),
                                sort_keys=True,
                                ensure_ascii=False,
                            )
                            fingerprint = hashlib.sha256(
                                fingerprint_payload.encode("utf-8")
                            ).hexdigest()

                            saved_key = "invoicepilot_saved_fingerprints"
                            if saved_key not in st.session_state:
                                st.session_state[saved_key] = set()

                            if fingerprint in st.session_state[saved_key]:
                                st.info(
                                    "These exact invoice details have "
                                    "already been saved during this session."
                                )
                            else:
                                invoice_id = db.add(reviewed)
                                st.session_state[saved_key].add(fingerprint)
                                st.success(
                                    f"Invoice saved successfully "
                                    f"(record #{invoice_id})."
                                )

                        except Exception as exc:
                            st.error(
                                "Could not save the invoice. "
                                "Your entered values have not been cleared. "
                                f"Error: {type(exc).__name__}: {exc}"
                            )

                except Exception as exc:
                    st.error(
                        f"Could not process {upload.name}: "
                        f"{type(exc).__name__}: {exc}"
                    )


# SAVED INVOICES
with tab_records:
    st.subheader("Invoice register")

    search = st.text_input(
        "Search supplier, invoice number, or source filename"
    )

    try:
        rows = db.list_all(search)
    except Exception as exc:
        rows = []
        st.error(
            f"Could not read saved invoices: {type(exc).__name__}: {exc}"
        )

    if rows:
        st.dataframe(
            pd.DataFrame(rows),
            width="stretch",
            hide_index=True,
        )

        st.download_button(
            "Download Excel",
            data=to_excel(rows),
            file_name="invoicepilot_invoices.xlsx",
            mime=(
                "application/vnd.openxmlformats-officedocument."
                "spreadsheetml.sheet"
            ),
        )

        st.download_button(
            "Download CSV",
            data=to_csv(rows),
            file_name="invoicepilot_invoices.csv",
            mime="text/csv; charset=utf-8",
        )

        st.divider()
        st.subheader("Edit or delete a saved record")

        ids = [row["id"] for row in rows]
        selected_id = st.selectbox("Select record ID", ids)
        selected = next(row for row in rows if row["id"] == selected_id)

        with st.form("edit_record"):
            c1, c2 = st.columns(2)

            with c1:
                e_supplier = st.text_input(
                    "Supplier",
                    value=selected.get("supplier", ""),
                )
                e_number = st.text_input(
                    "Invoice number",
                    value=selected.get("invoice_number", ""),
                )
                e_date = st.text_input(
                    "Invoice date",
                    value=selected.get("invoice_date", ""),
                )
                e_currency = st.text_input(
                    "Currency",
                    value=selected.get("currency", ""),
                    max_chars=3,
                )

            with c2:
                e_net = st.text_input(
                    "Net amount",
                    value=selected.get("net_amount", ""),
                )
                e_tax = st.text_input(
                    "Tax amount / VAT",
                    value=selected.get("tax_amount", ""),
                )
                e_total = st.text_input(
                    "Total amount (gross)",
                    value=selected.get("total_amount", ""),
                )
                e_payable = st.text_input(
                    "Payable amount",
                    value=selected.get("payable_amount", ""),
                )

            e_notes = st.text_input(
                "Notes",
                value=selected.get("extraction_notes", ""),
            )
            e_source = st.text_input(
                "Source filename",
                value=selected.get("source_filename", ""),
            )

            save_edit = st.form_submit_button("Update record")

        if save_edit:
            try:
                updated = InvoiceRecord(
                    supplier=e_supplier,
                    invoice_number=e_number,
                    invoice_date=e_date,
                    currency=e_currency,
                    net_amount=e_net,
                    tax_amount=e_tax,
                    total_amount=e_total,
                    payable_amount=e_payable,
                    source_filename=e_source,
                    extraction_notes=e_notes,
                )
                db.update(int(selected_id), updated)
                st.success("Record updated successfully.")
                st.rerun()
            except Exception as exc:
                st.error(
                    f"Could not update record: {type(exc).__name__}: {exc}"
                )

        if st.button("Delete selected record", type="secondary"):
            st.session_state["confirm_delete"] = int(selected_id)

        if st.session_state.get("confirm_delete") == int(selected_id):
            st.warning(
                "This permanently deletes the selected database record."
            )
            left, right = st.columns(2)

            if left.button("Confirm delete", type="primary"):
                try:
                    db.delete(int(selected_id))
                    st.session_state.pop("confirm_delete", None)
                    st.rerun()
                except Exception as exc:
                    st.error(
                        f"Could not delete record: "
                        f"{type(exc).__name__}: {exc}"
                    )

            if right.button("Cancel delete"):
                st.session_state.pop("confirm_delete", None)
                st.rerun()

    else:
        st.info("No invoices found. Upload a document to get started.")


# DUPLICATE CHECK
with tab_duplicates:
    st.subheader("Potential duplicate invoices")

    try:
        duplicates = db.possible_duplicates()

        if duplicates:
            st.warning(
                "These records share the same supplier and invoice number. "
                "Review them before deleting anything."
            )
            st.dataframe(
                pd.DataFrame(
                    duplicates,
                    columns=[
                        "First record ID",
                        "Second record ID",
                        "Invoice number",
                    ],
                ),
                width="stretch",
                hide_index=True,
            )
        else:
            st.success(
                "No duplicates found based on supplier + invoice number."
            )
    except Exception as exc:
        st.error(
            f"Could not check duplicates: {type(exc).__name__}: {exc}"
        )

# HELP & SETUP
with tab_help:
    st.subheader("What this version does")

    st.markdown("""
- Extracts text from digital PDFs.
- Uses OCR for scanned PDFs and images when enabled.
- Supports English and Greek invoice labels through editable heuristics.
- Extracts supplier, invoice number, date, currency, net, VAT, gross total,
  and payable amount.
- Lets you review and correct extracted values before saving.
- Stores invoice metadata in a local SQLite database.
- Exports invoice records to Excel and CSV.
- Flags potential duplicates by supplier and invoice number.

**Known limitations**

- Invoice layouts vary; extraction is best-effort, not guaranteed.
- PDF text extraction can rearrange table cells.
- Greek scanned invoices require Tesseract Greek language data (`ell`).
- Verify invoice numbers, dates, VAT, totals, and payable amounts.
- Uploaded originals are not saved by the app.
- The app does not submit VAT filings or synchronize with accounting software.
""")

    st.subheader("Install and run")
    st.code(
        "python -m venv .venv\n"
        "# Activate the environment (see README)\n"
        "pip install -r requirements.txt\n"
        "python -m streamlit run app.py",
        language="bash",
    )

    st.subheader("OCR setup")
    st.markdown("""
**Windows**
- Install Tesseract OCR and ensure `tesseract.exe` is on PATH.
- Install Greek language data (`ell`).

**macOS**
- Install Tesseract and ensure the Greek language data is available.

**Ubuntu/Debian**
- Install `tesseract-ocr`, `tesseract-ocr-eng`, and `tesseract-ocr-ell`.

If you only use text-based PDFs with selectable text, Tesseract is not required.
""")
