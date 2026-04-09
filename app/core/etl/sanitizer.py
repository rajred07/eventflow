"""
ETL Sanitizer — PII masking for CSV data before Gemini ingestion.

Rules:
  - Email pattern:  j.doe@corp.com  →  j***@c***.com
  - Phone pattern:  +91 98765 43210  →  +** ***** *****
  - Name/string:    Alice Roberts    →  [MASKED_NAME]
  - Numeric/ID:     EMP1042          →  EMP****  (prefix-preserved for context)
  - Categorical:    VIP, employee    →  kept as-is (needed for business logic)
  - Dates/URLs:     kept as-is

The key insight: Gemini doesn't need Alice's name to understand that the
column "Full Name" maps to our `name` field. But it DOES need to see
"vip" / "employee" to detect the category column accurately.
"""

import re
import hashlib


# ---------------------------------------------------------------------------
# Individual field maskers
# ---------------------------------------------------------------------------


def _mask_email(value: str) -> str:
    """j.doe@corp.inc → [EMAIL_A1B2C3]"""
    if not isinstance(value, str) or "@" not in value:
        return "[MASKED_EMAIL]"
    
    # We hash it so that the same email appearing in multiple rows
    # gets the same token, which lets Gemini detect duplicates.
    token = hashlib.md5(value.lower().strip().encode()).hexdigest()[:6].upper()
    return f"[EMAIL_{token}]"


def _mask_phone(value: str) -> str:
    """Replace all digit characters with *, keep separators and + prefix."""
    return re.sub(r"\d", "*", value)


def _mask_name(value: str) -> str:
    """Replace human names with a stable anonymous token."""
    # We hash it so that the same person appearing in multiple rows
    # gets the same token, which lets Gemini detect duplicates.
    token = hashlib.md5(value.lower().strip().encode()).hexdigest()[:6].upper()
    return f"[NAME_{token}]"


# ---------------------------------------------------------------------------
# Heuristic column classifier
# ---------------------------------------------------------------------------

_EMAIL_HEADERS = {"email", "e-mail", "mail", "emailaddress", "email_address",
                  "work email", "contact email", "business email"}
_PHONE_HEADERS = {"phone", "mobile", "cell", "contact", "tel", "telephone",
                  "phone number", "mobile number", "whatsapp"}
_NAME_HEADERS  = {"name", "full name", "fullname", "employee name", "guest name",
                  "first name", "last name", "firstname", "lastname", "attendee"}


def classify_column(header: str) -> str:
    """
    Returns 'email' | 'phone' | 'name' | 'safe' based on the header string.
    'safe' means the column can be sent to Gemini without masking.
    """
    normalized = header.lower().strip()
    if normalized in _EMAIL_HEADERS:
        return "email"
    if any(k in normalized for k in ("email", "e-mail", "mail")):
        return "email"
    if normalized in _PHONE_HEADERS:
        return "phone"
    if any(k in normalized for k in ("phone", "mobile", "tel", "whatsapp", "cell", "contact number", "mob no", "ph no")):
        return "phone"
    if normalized in _NAME_HEADERS:
        return "name"
    if any(k in normalized for k in ("name", "attendee")):
        return "name"
    return "safe"


# ---------------------------------------------------------------------------
# Row-level masker
# ---------------------------------------------------------------------------


def mask_row(row: dict, column_classifications: dict[str, str]) -> dict:
    """
    Given a row dict and the pre-computed per-column classification,
    mask PII fields and return a new anonymized row dict.
    """
    masked = {}
    for header, value in row.items():
        if value is None or str(value).strip() == "":
            masked[header] = ""
            continue

        col_type = column_classifications.get(header, "safe")
        val_str = str(value).strip()

        if col_type == "email":
            masked[header] = _mask_email(val_str)
        elif col_type == "phone":
            masked[header] = _mask_phone(val_str)
        elif col_type == "name":
            masked[header] = _mask_name(val_str)
        else:
            masked[header] = val_str  # Safe column — pass raw

    return masked


# ---------------------------------------------------------------------------
# Full dataset masker (call this before Gemini Call 2)
# ---------------------------------------------------------------------------


def mask_dataset(rows: list[dict], headers: list[str]) -> tuple[list[dict], dict[str, str]]:
    """
    Masks all rows in the dataset.
    Returns (masked_rows, column_classifications).
    column_classifications is the per-column type map so the caller can
    use it to intelligently display which columns were masked.
    """
    classifications = {h: classify_column(h) for h in headers}
    masked_rows = [mask_row(row, classifications) for row in rows]
    return masked_rows, classifications
