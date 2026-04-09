"""
ETL AI Service — Two-stage Gemini 2.5 Flash integration for CSV import.

Call 1: Schema Mapping  (cheap — headers only, no data)
Call 2: Full Validation (heavy — entire masked dataset sent for anomaly detection)

Uses google-genai SDK with strict JSON response mode (Pydantic schema enforcement).
Model: gemini-2.5-flash-preview-04-17
"""

import json
import logging
from typing import Any

from google import genai
from google.genai import types
from pydantic import BaseModel

from app.config import settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Gemini Client — lazy singleton
# ---------------------------------------------------------------------------

_client: genai.Client | None = None

def _get_client() -> genai.Client:
    global _client
    if _client is None:
        if not settings.GEMINI_API_KEY:
            raise RuntimeError("GEMINI_API_KEY is not set in .env")
        _client = genai.Client(api_key=settings.GEMINI_API_KEY)
    return _client

MODEL = "gemini-2.5-flash"


# ---------------------------------------------------------------------------
# Pydantic schemas for Gemini structured outputs
# ---------------------------------------------------------------------------


class ColumnMapping(BaseModel):
    """
    A single column mapping entry.
    csv_column: the raw header from the uploaded CSV
    db_field:   one of: 'name' | 'email' | 'phone' | 'category' | 'dietary_requirements' | 'extra_data' | 'skip'
    confidence: float 0.0–1.0
    reason:     one-sentence explanation
    """
    csv_column: str
    db_field: str
    confidence: float
    reason: str


class SchemaMappingResponse(BaseModel):
    """Gemini's response for Call 1 — schema mapping from headers only."""
    mappings: list[ColumnMapping]
    unmapped_columns: list[str]
    notes: str


class AnomalyFlag(BaseModel):
    """A single data problem flagged by Gemini."""
    row_index: int          # 0-based row number in the dataset
    column: str             # which column has the issue
    current_value: str      # what's in the cell (masked if PII)
    suggested_fix: str      # what Gemini thinks it should be
    issue_type: str         # 'format_error' | 'category_mismatch' | 'duplicate_suspect' | 'missing_required'
    severity: str           # 'error' | 'warning' | 'info'


class DuplicateGroup(BaseModel):
    """Two rows that Gemini suspects are the same person."""
    row_indices: list[int]
    reason: str


class FullValidationResponse(BaseModel):
    """Gemini's response for Call 2 — full dataset anomaly detection."""
    anomalies: list[AnomalyFlag]
    duplicate_suspects: list[DuplicateGroup]
    total_rows_analyzed: int
    clean_rows_count: int
    summary: str


# ---------------------------------------------------------------------------
# Call 1: Schema Mapping (Headers Only)
# ---------------------------------------------------------------------------


async def call1_map_schema(
    headers: list[str],
    sample_rows: list[dict],
    event_category_options: list[str],
    category_rules: dict | None = None,  # Full event.category_rules JSONB
) -> SchemaMappingResponse:
    """
    Call 1: Send only column headers + masked sample rows to Gemini.
    Returns the proposed column-to-database-field mapping.
    """
    client = _get_client()

    # Build a human-readable description of the category rules for Gemini
    category_context = ""
    if category_rules:
        lines = []
        for cat, rules in category_rules.items():
            allowed = rules.get("allowed_room_types", [])
            subsidy = rules.get("subsidy_per_night", 0)
            lines.append(
                f"  - '{cat}': allowed rooms={allowed}, subsidy=₹{subsidy}/night"
            )
        category_context = "\nEvent category business rules:\n" + "\n".join(lines)

    prompt = f"""You are a data integration specialist helping map a CSV file to a hotel/event guest database.

Our database schema for guests has these fields:
- name       → full name of the guest (required)
- email      → guest email address (required, must be unique per event)
- phone      → guest phone/mobile number (optional)
- category   → guest category, MUST be exactly one of: {event_category_options} (required)
- dietary_requirements → food/diet info (optional, maps to free-form text)
- extra_data → any other info like travel mode, t-shirt size, companion (optional)
- skip       → do not import this column at all
{category_context}

Use the category rules above to intelligently guess which category column values belong to.
For example, if a CSV has "Head Of Department" but category options are only ["employee","vip"],
suggest mapping "Head Of Department" → "vip" because it implies seniority.

CSV Headers to map: {headers}

Sample masked data rows (PII anonymized for privacy):
{json.dumps(sample_rows, indent=2)}

Instructions:
1. Map every CSV column header to exactly one db_field
2. Multiple CSV columns can map to 'extra_data' — they'll be merged as a JSON object
3. If a column is clearly irrelevant (row numbers, internal IDs), use 'skip'
4. For category values, note what transformations are needed (e.g. "VIP Access" → "vip")
5. Use the category_rules context to make smarter category guesses
6. Be conservative with confidence — only give 0.9+ if you're very sure

Return your analysis in the structured JSON format requested."""

    response = await client.aio.models.generate_content(
        model=MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=SchemaMappingResponse,
            temperature=0.1,
        ),
    )

    result = SchemaMappingResponse.model_validate_json(response.text)
    logger.info(f"[ETL Call 1] Mapped {len(result.mappings)} columns, {len(result.unmapped_columns)} unmapped")
    return result


# ---------------------------------------------------------------------------
# Call 2: Full Dataset Validation (All Rows, Masked)
# ---------------------------------------------------------------------------


async def call2_validate_dataset(
    masked_rows: list[dict],
    confirmed_mapping: list[dict],
    event_category_options: list[str],
    column_classifications: dict[str, str],
    category_rules: dict | None = None,
) -> FullValidationResponse:
    """
    Call 2: Send the ENTIRE masked dataset to Gemini for deep analysis.
    Returns anomalies, duplicate suspects, and a summary.
    """
    client = _get_client()

    masked_cols = [col for col, kind in column_classifications.items() if kind != "safe"]

    # Build category rules context for Gemini
    category_context = ""
    if category_rules:
        lines = []
        for cat, rules in category_rules.items():
            allowed = rules.get("allowed_room_types", [])
            subsidy = rules.get("subsidy_per_night", 0)
            lines.append(f"  - '{cat}': allowed rooms={allowed}, subsidy=\u20b9{subsidy}/night")
        category_context = "\nEvent category business rules:\n" + "\n".join(lines)

    prompt = f"""You are a senior data quality analyst validating a bulk guest import for a corporate event.

Guest database schema:
- name:     required string
- email:    required, must match user@domain.tld format
- phone:    optional
- category: REQUIRED — must be EXACTLY one of: {event_category_options}
- dietary_requirements: optional
- extra_data: optional
{category_context}

Confirmed column mapping (approved by planner):
{json.dumps(confirmed_mapping, indent=2)}

Privacy note — these columns are anonymized before reaching you:
Masked columns: {masked_cols}
  - Name columns:  [NAME_XXXXXX] tokens (SAME person = SAME token across rows)
  - Email columns: u***@d***.tld format
  - Phone columns: +** **** **** format

Your task — analyze ALL {len(masked_rows)} rows:
1. FORMAT ERRORS: Email not matching u@d.tld, completely empty required fields
2. CATEGORY MISMATCHES: Any category value that is NOT exactly one of {event_category_options}.
   — Flag EVERY such row. Use the event business rules to deduce and suggest the correct exact category.
   — For example, if the value is "L3 - Employee", the suggested fix should be "employee".
   — If the value is "Director", use context to suggest "vip".
3. DUPLICATE SUSPECTS: Rows sharing the same masked email token (u***@d***.tld matches) 
   or same [NAME_XXXXXX] token — these are likely the same person
4. MISSING REQUIRED: Empty/null name, email, or category

Use row_index starting at 0 for the first row.

Full masked dataset ({len(masked_rows)} rows):
{json.dumps(masked_rows, indent=2)}"""

    response = await client.aio.models.generate_content(
        model=MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=FullValidationResponse,
            temperature=0.1,
        ),
    )

    result = FullValidationResponse.model_validate_json(response.text)
    logger.info(
        f"[ETL Call 2] {result.total_rows_analyzed} rows analyzed. "
        f"{len(result.anomalies)} anomalies, {len(result.duplicate_suspects)} duplicate groups."
    )
    return result
