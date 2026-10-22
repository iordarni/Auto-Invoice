# Auto-Invoice

A Python application for extracting and managing invoice metadata.

## Features

- Upload digital PDFs and common image formats.
- Extract text from PDFs; optional OCR for scanned PDFs and images.
- Best-effort extraction of supplier, invoice number/date, currency, net/tax/total.
- Review and correct fields before saving.
- SQLite storage, search, edit/delete, duplicate checks.
- Excel and CSV exports.

## Important limitations

This is a starter product, not accounting or tax software. Invoice formats differ, so extracted values must be checked by a human. The app does not store the original uploaded files. OCR for scanned documents requires the Tesseract executable in addition to the Python package. The current database stores amounts as text to avoid silently introducing floating-point rounding; values are normalized to two decimal places where possible.

## 1. Requirements

- Python 3.11 or newer recommended.
- Internet access for installing Python dependencies.
- Tesseract OCR only if you want to process scanned PDFs or image receipts.

## 2. Create a virtual environment

Open a terminal in this project folder.

### Windows PowerShell

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

If PowerShell blocks activation, use Command Prompt instead:

```bat
.venv\Scripts\activate.bat
```

### macOS / Linux

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
```

## 3. Run the app locally

```bash
streamlit run app.py
```

Streamlit should open a browser tab. If not, open the local URL shown in the terminal, usually `http://localhost:8501`.

## 4. OCR setup (optional)

Text-based PDFs do not require Tesseract. For scans and image receipts, install Tesseract:

- Windows: install a Tesseract OCR distribution and add its installation directory to PATH.
- macOS with Homebrew: `brew install tesseract`
- Ubuntu/Debian: `sudo apt-get update && sudo apt-get install tesseract-ocr`

Restart your terminal after installation and run the app again. If OCR is unavailable, the app explains that and lets you enter the fields manually.

## 5. How to use

1. Open **Upload invoices**.
2. Upload one or more PDFs or images.
3. Check every extracted value in the review form.
4. Click **Save invoice**.
5. Use **Saved invoices** to search, edit, delete, and export.
6. Use **Duplicate check** to review matching supplier/invoice-number pairs.

## Architecture

```text
Streamlit UI
    |
    +--> extraction.py: PDF text / OCR
    |
    +--> processing.py: normalization + validation
    |
    +--> database.py: SQLite persistence
    |
    +--> exports.py: Excel / CSV
```
