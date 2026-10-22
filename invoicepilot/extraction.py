"""Text extraction and parsing for English and Greek invoices."""
from __future__ import annotations

import io
import re
import unicodedata
from datetime import datetime
from decimal import Decimal, InvalidOperation

import pytesseract

# Update this path if Tesseract is installed in a different location.
pytesseract.pytesseract.tesseract_cmd = (
    r"C:\Program Files\Tesseract-OCR\tesseract.exe"
)

SUPPORTED_EXTENSIONS = {
    ".pdf", ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp"
}


def _ocr_image(image, lang: str = "eng") -> str:
    """Extract text using the available Greek and English Tesseract packs."""
    try:
        available = set(pytesseract.get_languages(config=""))
        candidates = [
            language
            for language in ("ell", "eng", "ell+eng")
            if all(part in available for part in language.split("+"))
        ]

        if not candidates:
            return pytesseract.image_to_string(image)

        results: dict[str, str] = {}
        for language in candidates:
            try:
                results[language] = pytesseract.image_to_string(
                    image, lang=language, config="--oem 1 --psm 3"
                )
            except Exception:
                continue

        if not results:
            return pytesseract.image_to_string(image, lang=candidates[0])

        def score(ocr_text: str, language: str) -> float:
            ocr_text = ocr_text.strip()
            if not ocr_text:
                return float("-inf")
            letters = [ch for ch in ocr_text if ch.isalpha()]
            if not letters:
                return 0.0
            greek_count = sum(
                "\u0370" <= ch <= "\u03FF" or "\u1F00" <= ch <= "\u1FFF"
                for ch in letters
            )
            latin_count = sum(ch.lower() in "abcdefghijklmnopqrstuvwxyz" for ch in letters)
            total = len(letters)
            greek_ratio = greek_count / total
            latin_ratio = latin_count / total
            word_count = len(re.findall(r"\b[\w'-]+\b", ocr_text, flags=re.UNICODE))
            noise = ocr_text.count("\ufffd") + ocr_text.count("\x00")
            quality = min(word_count, 100) * 0.1 - noise * 5
            if language == "ell":
                quality += greek_ratio * 10
            elif language == "eng":
                quality += latin_ratio * 10
            else:
                quality += min(greek_ratio, latin_ratio) * 5
            return quality

        best = max(results, key=lambda language: score(results[language], language))
        return results[best]
    except Exception:
        try:
            return pytesseract.image_to_string(image, lang=lang)
        except Exception:
            return ""


def extract_text(
    file_bytes: bytes,
    filename: str,
    use_ocr: bool = True,
) -> tuple[str, str]:
    """Extract text from a PDF or image and return text plus a status note."""
    from PIL import Image

    extension = (
        "." + filename.rsplit(".", 1)[-1].lower()
        if "." in filename
        else ""
    )
    if extension not in SUPPORTED_EXTENSIONS:
        raise ValueError(f"Unsupported file type: {extension or filename}")

    if extension == ".pdf":
        document = None
        pdf_error = "PDF extraction failed."
        try:
            import pymupdf

            document = pymupdf.open(stream=file_bytes, filetype="pdf")
            text = "\n".join(page.get_text("text") for page in document).strip()
            if text:
                return text, "Text extracted from PDF."
            if not use_ocr:
                return "", "No selectable PDF text found; OCR is disabled."

            pages = []
            for page in document:
                pixmap = page.get_pixmap(
                    matrix=pymupdf.Matrix(2, 2), alpha=False
                )
                image = Image.open(io.BytesIO(pixmap.tobytes("png")))
                pages.append(_ocr_image(image))
            return "\n".join(pages).strip(), "Text extracted from PDF using OCR."
        except ImportError as exc:
            pdf_error = (
                "PyMuPDF is not installed. Install it with "
                "'python -m pip install pymupdf'. Details: " + str(exc)
            )
        except Exception as exc:
            pdf_error = f"PDF extraction failed: {exc}"
        finally:
            if document is not None:
                document.close()

        if not use_ocr:
            return "", pdf_error
        try:
            from pdf2image import convert_from_bytes

            pages = convert_from_bytes(file_bytes)
            text = "\n".join(_ocr_image(page) for page in pages).strip()
            return text, "PDF processed using OCR."
        except Exception as exc:
            return "", (
                f"{pdf_error} OCR fallback failed: {exc}. "
                "Check PDF dependencies, Poppler, and Tesseract."
            )

    if not use_ocr:
        return "", "Image OCR is disabled."
    try:
        image = Image.open(io.BytesIO(file_bytes))
        image.load()
        return _ocr_image(image), "Text extracted from image using OCR."
    except Exception as exc:
        return "", f"Image OCR failed: {exc}"


def parse_invoice_text(text: str) -> dict:
    """Extract common invoice fields from Greek or English invoice text."""
    lines = [line.strip() for line in text.splitlines() if line.strip()]

    def plain(value: str) -> str:
        """Case-fold and remove accents for matching labels."""
        value = unicodedata.normalize("NFKD", value.casefold())
        return "".join(ch for ch in value if not unicodedata.combining(ch)).replace("ς", "σ")

    normalized = [plain(line) for line in lines]

    def clean(value: str) -> str:
        return value.strip(" \t:;|[]{}()<>.,-_=~'\"")

    def fix_ocr_digits(value: str) -> str:
        return value.translate(str.maketrans({
            "O": "0", "o": "0", "Ο": "0", "ο": "0",
            "Θ": "0", "θ": "0",
        }))

    def normalize_amount(value: str) -> str:
        value = fix_ocr_digits(value.strip())
        value = re.sub(r"(?i)\bEUR\b|€", "", value)
        value = value.replace(" ", "").strip("=:;|[]{}()")
        if not value or not re.fullmatch(r"-?[\d.,/]+", value):
            return ""

        if "/" in value:
            if re.fullmatch(r"-?\d+/\d{2}", value):
                value = value.replace("/", ".")
            else:
                return ""

        if "," in value and "." in value:
            if value.rfind(",") > value.rfind("."):
                value = value.replace(".", "").replace(",", ".")
            else:
                value = value.replace(",", "")
        elif "," in value:
            tail = value.rsplit(",", 1)[-1]
            value = value.replace(",", "." if len(tail) in (1, 2) else "")
        elif "." in value:
            tail = value.rsplit(".", 1)[-1]
            if len(tail) > 2:
                value = value.replace(".", "")
        elif value.lstrip("-").isdigit():
            digits = value.lstrip("-")
            # Avoid converting small identifiers (e.g. 19 or 24) to money.
            if len(digits) >= 4:
                sign = "-" if value.startswith("-") else ""
                value = sign + digits[:-2] + "." + digits[-2:]

        try:
            return format(Decimal(value).quantize(Decimal("0.01")), "f")
        except (InvalidOperation, ValueError):
            return ""

    amount_pattern = re.compile(
        r"(?<![\w])[-+]?"
        r"(?:[0-9OoΟοΘθ]{1,3}(?:[.,][0-9OoΟοΘθ]{3})+(?:[.,][0-9OoΟοΘθ]{1,2})?"
        r"|[0-9OoΟοΘθ]+(?:[.,][0-9OoΟοΘθ]{1,2})?)"
        r"(?![\w])"
    )

    def amounts_in(line: str) -> list[str]:
        values = []
        for match in amount_pattern.finditer(line):
            value = normalize_amount(match.group(0))
            if value:
                values.append(value)
        return values

    date_pattern = re.compile(
        r"(?<!\d)(?:\d{4}-\d{1,2}-\d{1,2}"
        r"|\d{1,2}[./-]\d{1,2}[./-]\d{2,4}"
        r"|[0-9OoΟοΘθ]{1,2}[./-][0-9OoΟοΘθ]{1,2}[./-][0-9OoΟοΘθ]{2,4})(?!\d)"
    )

    def parse_date(value: str) -> str:
        value = fix_ocr_digits(value.strip())
        for fmt in (
            "%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y",
            "%d/%m/%y", "%d-%m-%y", "%d.%m.%y",
        ):
            try:
                return datetime.strptime(value, fmt).date().isoformat()
            except ValueError:
                pass
        return ""

    # Supplier: use the first issuer "Επωνυμία", before the customer section.
    supplier = ""
    customer_idx = next(
        (i for i, label in enumerate(normalized) if "στοιχεια πελατη" in label),
        len(lines),
    )
    for i in range(customer_idx):
        if "επωνυμια" not in normalized[i] and "supplier" not in normalized[i]:
            continue
        # Do not use offsets from accent-normalized text to slice original text.
        match = re.search(r"(?i)Επωνυμία\s*:?\s*(.*)", lines[i])
        if not match:
            match = re.search(r"(?i)supplier\s*:?\s*(.*)", lines[i])
        remainder = clean(match.group(1)) if match else ""
        if remainder:
            supplier = remainder
            break
        if i + 1 < len(lines):
            candidate = clean(lines[i + 1])
            if candidate:
                supplier = candidate
                break

    # Invoice date: prefer a date near the invoice-header "Ημερομηνία" label.
    invoice_date = ""
    date_label_idx = next(
        (
            i for i, label in enumerate(normalized)
            if label == "ημερομηνια" or label.startswith("ημερομηνια ")
            or label == "invoice date" or label.startswith("invoice date ")
        ),
        None,
    )
    if date_label_idx is not None:
        for candidate in lines[date_label_idx:date_label_idx + 8]:
            match = date_pattern.search(candidate)
            if match:
                invoice_date = parse_date(match.group(0))
                if invoice_date:
                    break
    if not invoice_date:
        for candidate in lines:
            match = date_pattern.search(candidate)
            if match:
                invoice_date = parse_date(match.group(0))
                if invoice_date:
                    break

    # Invoice number: find short numeric values between "Α.Α." and the date.
    invoice_number = ""
    aa_idx = next(
        (i for i, label in enumerate(normalized)
         if re.fullmatch(r"α\.?\s*α\.?", label.strip())),
        None,
    )
    if aa_idx is not None:
        date_idx = None
        for j in range(aa_idx + 1, min(aa_idx + 20, len(lines))):
            if date_pattern.search(lines[j]):
                date_idx = j
                break
        if date_idx is not None:
            candidates = []
            for candidate in lines[aa_idx + 1:date_idx]:
                candidate = fix_ocr_digits(candidate.strip())
                # Ignore long MARK/payment references and zero-only artifacts.
                if re.fullmatch(r"\d{1,8}", candidate) and int(candidate) > 0:
                    candidates.append(candidate)
            if candidates:
                invoice_number = candidates[-1]

    if not invoice_number:
        for i, label in enumerate(normalized):
            if re.search(r"invoice\s*(?:no\.?|number)", label):
                match = re.search(r"(?<!\d)\d{1,8}(?!\d)", lines[i])
                if match:
                    invoice_number = match.group(0)
                    break

    # Net, VAT and gross totals: use the first numeric rows directly below
    # the standalone "Σύνολα" heading. For this invoice they are:
    # discount, net, VAT, gross.
    net_amount = ""
    tax_amount = ""
    total_amount = ""
    summary_idx = next(
        (i for i, label in enumerate(normalized)
         if re.fullmatch(r"συνολα\s*:?", label.strip())
         or label.strip() in ("totals", "total")),
        None,
    )

    if summary_idx is not None:
        summary_values = []
        for candidate in lines[summary_idx + 1:summary_idx + 12]:
            label = plain(candidate)
            # The summary amount rows end when the separate label list begins.
            if any(marker in label for marker in (
                "συνολ. αξια", "συνολικη αξια", "withholding", "grand total",
            )):
                break
            values = amounts_in(candidate)
            if values:
                summary_values.extend(values)
            # Stop after the first four amount cells: discount, net, VAT, gross.
            if len(summary_values) >= 4:
                break

        if len(summary_values) >= 4:
            net_amount, tax_amount, total_amount = summary_values[1:4]
        elif len(summary_values) == 3:
            net_amount, tax_amount, total_amount = summary_values
        elif len(summary_values) == 2:
            net_amount, total_amount = summary_values

    # Label-based fallbacks for other invoice layouts.
    for i, label in enumerate(normalized):
        if not net_amount and any(term in label for term in (
            "καθαρη αξια", "net amount", "subtotal",
        )):
            values = amounts_in(lines[i])
            if values:
                net_amount = values[-1]

        if not tax_amount and (
            re.fullmatch(r"φπα(?:\s*\(?\s*€?\s*\)?)?\s*:?", label)
            or "vat amount" in label or "tax amount" in label
        ):
            values = amounts_in(lines[i])
            if not values and i + 1 < len(lines):
                values = amounts_in(lines[i + 1])
            if values:
                tax_amount = values[-1]

        if not total_amount and any(term in label for term in (
            "grand total", "total amount", "συνολ. αξια", "συνολικη αξια",
        )):
            values = amounts_in(lines[i])
            if values:
                total_amount = values[-1]

    # Payable amount may appear immediately before the "Πληρωτέο (€):" label.
    payable_amount = ""
    for i, label in enumerate(normalized):
        if "πληρωτεο" not in label and "amount payable" not in label:
            continue
        values = amounts_in(lines[i])
        if values:
            payable_amount = values[-1]
        elif i > 0:
            values = amounts_in(lines[i - 1])
            if values:
                payable_amount = values[-1]
        elif i + 1 < len(lines):
            values = amounts_in(lines[i + 1])
            if values:
                payable_amount = values[-1]
        break

    # Reconcile VAT only if net and gross are known and the recognized VAT
    # does not match the arithmetic difference.
    if net_amount and total_amount:
        try:
            difference = (
                Decimal(total_amount) - Decimal(net_amount)
            ).quantize(Decimal("0.01"))
            if difference >= 0 and (
                not tax_amount
                or abs(Decimal(tax_amount) - difference) > Decimal("0.02")
            ):
                tax_amount = format(difference, "f")
        except (InvalidOperation, ValueError):
            pass

    currency = (
        "EUR"
        if re.search(r"€|\bEUR\b|πληρωτεο", plain(text), re.IGNORECASE)
        else ""
    )

    # Prefer remarks text; otherwise retain the declaration preceding remarks.
    notes = ""
    remarks_idx = next(
        (i for i, label in enumerate(normalized)
         if "παρατηρησεισ" in label or "remarks" in label),
        None,
    )
    if remarks_idx is not None:
        parts = []
        heading_match = re.search(r"(?i)Παρατηρήσεις\s*:?\s*(.*)", lines[remarks_idx])
        if heading_match and heading_match.group(1).strip():
            parts.append(heading_match.group(1).strip())
        for candidate in lines[remarks_idx + 1:]:
            label = plain(candidate)
            if any(marker in label for marker in (
                "αναλυση φορων", "σελιδα", "η ευθυνη για το περιεχομενο",
                "εκδοθηκε απο την εφαρμογη",
            )):
                break
            parts.append(candidate)
        notes = " ".join(parts).strip()

    if not notes:
        for i, label in enumerate(normalized):
            if "υπαγομαι στισ διαταξεισ" in label:
                parts = [lines[i]]
                for j in range(i + 1, len(lines)):
                    if any(marker in normalized[j] for marker in (
                        "παρατηρησεισ", "αναλυση φορων", "σελιδα",
                    )):
                        break
                    parts.append(lines[j])
                notes = " ".join(parts).strip()
                break

    return {
        "supplier": supplier,
        "invoice_number": invoice_number,
        "invoice_date": invoice_date,
        "currency": currency,
        "net_amount": net_amount,
        "tax_amount": tax_amount,
        "total_amount": total_amount,
        "payable_amount": payable_amount,
        "extraction_notes": notes[:1000],
    }
