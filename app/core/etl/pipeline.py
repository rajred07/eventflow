"""
ETL Pipeline Service — Orchestrates the full CSV import flow.

This module handles everything EXCEPT the Gemini calls themselves:
  - CSV/Excel parsing with pandas
  - PII classification and masking
  - Applying the confirmed mapping to the full unmasked dataset
  - Final deterministic validation (regex, duplicates, category check)
  - Delegating bulk insert to the existing bulk_create_guests service

The AI calls (Call 1 and Call 2) are triggered from the API route layer.
This keeps the service pure and testable without mocking Gemini.
"""

import io
import re
import uuid
import logging
from typing import Any

import pandas as pd

from app.core.etl.sanitizer import mask_dataset, classify_column

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# CSV / Excel Parsing
# ---------------------------------------------------------------------------


def parse_upload(file_bytes: bytes, filename: str) -> tuple[list[str], list[dict]]:
    """
    Parse uploaded CSV or Excel bytes into (headers, rows).
    Returns a list of column headers and a list of row dicts.

    Raises ValueError if the file is empty or unparseable.
    """
    try:
        if filename.lower().endswith((".xlsx", ".xls")):
            df = pd.read_excel(io.BytesIO(file_bytes), dtype=str)
        else:
            df = pd.read_csv(io.BytesIO(file_bytes), dtype=str)
    except Exception as e:
        raise ValueError(f"Could not parse file '{filename}': {e}")

    # Strip whitespace from headers
    df.columns = [str(c).strip() for c in df.columns]

    # Drop completely empty rows
    df = df.dropna(how="all")

    if df.empty:
        raise ValueError("The uploaded file has no data rows.")

    headers = list(df.columns)
    rows = df.where(pd.notna(df), None).to_dict(orient="records")
    return headers, rows


def get_sample_rows(rows: list[dict], n: int = 5) -> list[dict]:
    """
    Returns up to n representative sample rows for Call 1.
    Picks from different parts of the dataset to maximize variety.
    """
    if len(rows) <= n:
        return rows
    # Pick first, last, and middle-spread rows
    indices = [0, len(rows) - 1] + [len(rows) // (n - 1) * i for i in range(1, n - 1)]
    indices = sorted(set(indices))[:n]
    return [rows[i] for i in indices]


# ---------------------------------------------------------------------------
# Pre-masking for Call 1 (just the sample rows)
# ---------------------------------------------------------------------------


def prepare_call1_payload(headers: list[str], rows: list[dict]) -> tuple[list[dict], dict[str, str]]:
    """
    Masks a small sample of rows for Call 1 (schema mapping).
    Returns (masked_sample_rows, column_classifications).
    """
    sample = get_sample_rows(rows, n=5)
    masked_samples, classifications = mask_dataset(sample, headers)
    return masked_samples, classifications


# ---------------------------------------------------------------------------
# Pre-masking for Call 2 (full dataset)
# ---------------------------------------------------------------------------


def prepare_call2_payload(rows: list[dict], headers: list[str]) -> tuple[list[dict], dict[str, str]]:
    """
    Masks ALL rows for Call 2 (full validation).
    Returns (all_masked_rows, column_classifications).
    """
    return mask_dataset(rows, headers)



# ---------------------------------------------------------------------------
# Apply Confirmed Mapping to the full UNMASKED dataset
# ---------------------------------------------------------------------------


def apply_mapping(
    rows: list[dict],
    mapping: list[dict],
) -> list[dict]:
    """
    Applies the confirmed column mapping to the original (unmasked) rows.

    db_field special handling:
      - 'skip' → column is ignored entirely
      - 'extra_data' → multiple source columns get merged into the extra_data dict
      - 'dietary_requirements' → similar merge
      - all others → 1:1 rename

    Returns a list of normalized dicts with our standard schema keys.
    """
    # Build a lookup: csv_column → db_field
    col_map: dict[str, str] = {m["csv_column"]: m["db_field"] for m in mapping}

    normalized = []
    for row in rows:
        record: dict[str, Any] = {
            "name": None,
            "email": None,
            "phone": None,
            "category": None,
            "dietary_requirements": {},
            "extra_data": {},
        }
        for csv_col, value in row.items():
            db_field = col_map.get(csv_col, "skip")
            if db_field == "skip" or value is None:
                continue

            val = str(value).strip() if value is not None else None
            if not val:
                continue

            if db_field in ("name", "email", "phone", "category"):
                record[db_field] = val
            elif db_field == "dietary_requirements":
                record["dietary_requirements"][csv_col] = val
            elif db_field == "extra_data":
                record["extra_data"][csv_col] = val

        normalized.append(record)
    return normalized


# ---------------------------------------------------------------------------
# Apply Planner Corrections from HitL Grid
# ---------------------------------------------------------------------------


def apply_planner_corrections(
    rows: list[dict],
    corrections: list[dict],
) -> list[dict]:
    """
    Applies row-level corrections from the HitL data grid.
    corrections: list of {row_index, column, new_value}
    Mutates and returns the normalized rows in-place.
    """
    for correction in corrections:
        idx = correction["row_index"]
        col = correction["column"]
        new_val = correction["new_value"]
        if 0 <= idx < len(rows):
            rows[idx][col] = new_val
    return rows


# ---------------------------------------------------------------------------
# Final Deterministic Validation (No AI)
# ---------------------------------------------------------------------------

EMAIL_REGEX = re.compile(r"^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$")


def validate_and_clean(
    rows: list[dict],
    valid_categories: list[str],
    existing_emails: set[str],
) -> tuple[list[dict], list[dict]]:
    """
    Final deterministic pass: validates the fully-mapped, planner-corrected rows.

    Rules:
      - Row must have name (non-empty)
      - Row must have a valid email (matches regex)
      - Email must not already exist in the DB (skip rule)
      - Category must be in valid_categories (case-insensitive)

    Returns:
      clean_rows   — rows that passed ALL checks, ready for DB insert
      error_rows   — rows that failed, each annotated with 'error' key
    """
    clean: list[dict] = []
    errors: list[dict] = []

    seen_in_batch: set[str] = set()

    for i, row in enumerate(rows):
        row_errors = []

        # 1. Name check
        name = (row.get("name") or "").strip()
        if not name:
            row_errors.append("Missing name")

        # 2. Email check
        email = (row.get("email") or "").strip().lower()
        if not email:
            row_errors.append("Missing email")
        elif not EMAIL_REGEX.match(email):
            row_errors.append(f"Invalid email format: '{email}'")
        elif email in existing_emails:
            row_errors.append(f"Email '{email}' already exists — skipped")
        elif email in seen_in_batch:
            row_errors.append(f"Duplicate email within upload: '{email}'")
        else:
            seen_in_batch.add(email)

        # 3. Category check
        category = (row.get("category") or "").strip().lower()
        if not category:
            row_errors.append("Missing category")
        elif category not in [c.lower() for c in valid_categories]:
            row_errors.append(
                f"Unknown category '{category}'. Valid: {valid_categories}"
            )
        else:
            row["category"] = category  # Normalize to lowercase

        if row_errors:
            errors.append({**row, "_row_index": i, "_errors": row_errors})
        else:
            clean.append(row)

    return clean, errors


# ---------------------------------------------------------------------------
# Build yield warning (Smart Category Yield Management)
# ---------------------------------------------------------------------------


def check_yield_warnings(
    rows: list[dict],
    room_inventory: dict[str, int],
) -> list[dict]:
    """
    Cross-checks import quantities against live room inventory.
    Returns a list of warning dicts if the import would overflow a category.

    room_inventory example: {"standard": 2, "deluxe": 3, "suite": 1}
    This function is called BEFORE the bulk insert, during the validation step.
    """
    from collections import Counter
    category_counts = Counter((r.get("category") or "").lower() for r in rows)
    warnings = []

    for category, count in category_counts.items():
        if category in room_inventory:
            available = room_inventory[category]
            if count > available:
                overflow = count - available
                warnings.append({
                    "category": category,
                    "importing": count,
                    "available_rooms": available,
                    "overflow": overflow,
                    "message": (
                        f"You are importing {count} '{category}' guests, "
                        f"but only {available} rooms are available. "
                        f"{overflow} guests will be auto-placed on the waitlist."
                    ),
                })
    return warnings
