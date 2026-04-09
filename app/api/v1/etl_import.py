"""
ETL Import Routes — AI-powered guest CSV import with Human-in-the-Loop.

Two-stage async flow:

  STAGE 1 ─ POST /events/{event_id}/import/analyze
    ├── Upload CSV → parse headers + 5-row sample
    ├── Gemini Call 1: headers → column mapping proposal
    └── Returns: mapping proposal + column_classifications
            Frontend: HitL Mapper (planner confirms/overrides mapping)

  STAGE 2 ─ POST /events/{event_id}/import/validate
    ├── Receives: confirmed mapping + full file (re-upload or session-stored bytes)
    ├── Masks ALL rows with PII sanitizer
    ├── Gemini Call 2: full masked data → anomaly report
    └── Returns: validation_report (anomalies, duplicates, yield warnings)
            Frontend: HitL Data Grid (planner fixes red cells, approves)

  STAGE 3 ─ POST /events/{event_id}/import/commit
    ├── Receives: confirmed mapping + planner corrections + rows
    ├── Applies corrections to unmasked rows
    ├── Runs final deterministic validation (email regex, category, dedup)
    └── Triggers Celery bulk_insert task → returns job status
            Frontend: Progress bar, then import summary
"""

import uuid
import logging
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.rbac import require_role
from app.core.etl.ai_service import (
    call1_map_schema,
    call2_validate_dataset,
    ColumnMapping,
    SchemaMappingResponse,
    FullValidationResponse,
)
from app.core.etl.pipeline import (
    parse_upload,
    prepare_call1_payload,
    prepare_call2_payload,
    apply_mapping,
    apply_planner_corrections,
    validate_and_clean,
    check_yield_warnings,
)
from app.core.guests.service import bulk_create_guests
from app.db.session import get_db
from app.models.event import Event
from app.models.guest import Guest
from app.models.room_block_allotment import RoomBlockAllotment
from app.models.room_block import RoomBlock
from app.models.user import User
from app.schemas.guest import GuestBulkCreate, GuestBulkCreateItem, GuestCreate

logger = logging.getLogger(__name__)
router = APIRouter(tags=["ETL Import"])


# ---------------------------------------------------------------------------
# Pydantic I/O models for the 3 endpoints
# ---------------------------------------------------------------------------


class AnalyzeResponse(BaseModel):
    """Returned after Stage 1 (CSV upload + Call 1)."""
    headers: list[str]
    total_rows: int
    proposed_mapping: list[dict]
    unmapped_columns: list[str]
    column_classifications: dict[str, str]
    event_categories: list[str]
    ai_notes: str


class ValidateRequest(BaseModel):
    """
    Sent by the frontend after the planner confirms the column mapping.
    The raw_rows are the full unmasked rows parsed in Stage 1.
    The frontend re-sends them as JSON (they were returned from /analyze).
    """
    confirmed_mapping: list[dict]          # [{csv_column, db_field, ...}]
    raw_rows: list[dict[str, Any]]         # Full unmasked rows from Stage 1


class ValidationReport(BaseModel):
    """Returned after Stage 2 (Gemini Call 2 + yield warnings)."""
    anomalies: list[dict]
    duplicate_suspects: list[dict]
    yield_warnings: list[dict]
    total_rows: int
    clean_rows_estimate: int
    summary: str
    # These are the normalized rows (mapping applied) ready for Stage 3.
    # The frontend populates the HitL grid with these, then sends corrections back.
    normalized_rows: list[dict]


class Correction(BaseModel):
    """A single cell correction from the planner's HitL grid."""
    row_index: int
    column: str
    new_value: str


class CommitRequest(BaseModel):
    """Sent by the planner when they click 'Confirm & Import All'."""
    confirmed_mapping: list[dict]
    normalized_rows: list[dict[str, Any]]
    corrections: list[Correction] = []


class CommitResponse(BaseModel):
    """Result summary after Stage 3 (bulk DB insert)."""
    created: int
    skipped: int
    errors: list[str]
    yield_warnings: list[dict]


# ---------------------------------------------------------------------------
# Helper: get event with category rules
# ---------------------------------------------------------------------------


async def _get_event(event_id: uuid.UUID, tenant_id: uuid.UUID, db: AsyncSession) -> Event:
    result = await db.execute(
        select(Event).where(Event.id == event_id, Event.tenant_id == tenant_id)
    )
    event = result.scalar_one_or_none()
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
    return event


async def _get_room_inventory(event_id: uuid.UUID, db: AsyncSession) -> dict[str, int]:
    """
    Returns available rooms per room_type for this event.
    Used in yield warning checks.
    """
    result = await db.execute(
        select(RoomBlockAllotment)
        .join(RoomBlock, RoomBlock.id == RoomBlockAllotment.room_block_id)
        .where(RoomBlock.event_id == event_id)
    )
    allotments = result.scalars().all()
    inventory: dict[str, int] = {}
    for a in allotments:
        available = a.total_rooms - a.held_rooms - a.booked_rooms
        inventory[a.room_type] = inventory.get(a.room_type, 0) + available
    return inventory


# ---------------------------------------------------------------------------
# STAGE 1: Analyze — Upload CSV, run Call 1
# ---------------------------------------------------------------------------


@router.post(
    "/events/{event_id}/import/analyze",
    response_model=AnalyzeResponse,
    summary="Stage 1: Upload CSV and get AI column mapping proposal",
)
async def analyze_import(
    event_id: uuid.UUID,
    file: UploadFile = File(..., description="CSV or Excel file to import"),
    current_user: User = Depends(require_role(["admin", "planner"])),
    db: AsyncSession = Depends(get_db),
):
    """
    Parses the uploaded file and runs Gemini Call 1 (headers-only mapping).

    Returns the AI's proposed column mapping and the raw rows in the response
    so the frontend can display the HitL mapper and store rows client-side
    for Stage 2 (no file re-upload needed).

    Frontend connects to:
      - proposed_mapping → display the column mapper dropdown for planner review
      - column_classifications → show a PII shield icon on masked columns
      - raw_rows → store in state for Stage 2 request body
    """
    event = await _get_event(event_id, current_user.tenant_id, db)
    event_categories = list((event.category_rules or {}).keys())

    # 1. Parse file
    file_bytes = await file.read()
    try:
        headers, rows = parse_upload(file_bytes, file.filename or "import.csv")
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    # 2. Mask sample rows for Call 1 (PII safe)
    masked_samples, col_classifications = prepare_call1_payload(headers, rows)

    # 3. Gemini Call 1 — headers + 5 masked sample rows
    try:
        ai_result: SchemaMappingResponse = await call1_map_schema(
            headers=headers,
            sample_rows=masked_samples,
            event_category_options=event_categories,
            category_rules=event.category_rules or {},
        )
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        logger.exception("Gemini Call 1 failed")
        raise HTTPException(status_code=502, detail=f"AI mapping failed: {e}")

    return AnalyzeResponse(
        headers=headers,
        total_rows=len(rows),
        proposed_mapping=[m.model_dump() for m in ai_result.mappings],
        unmapped_columns=ai_result.unmapped_columns,
        column_classifications=col_classifications,
        event_categories=event_categories,
        ai_notes=ai_result.notes,
        # NB: raw_rows NOT returned here — frontend keeps them in memory from upload
        # To avoid huge payloads, we return only the metadata. The frontend re-sends
        # rows in Stage 2 /validate (see ValidateRequest.raw_rows).
        # For large files (500+ rows) this should be moved to Redis session storage.
    )


# ---------------------------------------------------------------------------
# STAGE 2: Validate — Run Call 2 on full masked dataset
# ---------------------------------------------------------------------------


@router.post(
    "/events/{event_id}/import/validate",
    response_model=ValidationReport,
    summary="Stage 2: Full AI validation + yield warnings after planner confirms mapping",
)
async def validate_import(
    event_id: uuid.UUID,
    body: ValidateRequest,
    current_user: User = Depends(require_role(["admin", "planner"])),
    db: AsyncSession = Depends(get_db),
):
    """
    Takes the planner's confirmed column mapping and the full raw rows,
    masks ALL rows, sends them to Gemini for deep validation, and
    cross-checks against live room inventory.

    Returns the normalized rows (mapping already applied) + all anomalies
    so the frontend can populate the HitL Data Grid and highlight issues.

    Frontend connects to:
      - anomalies → highlight rows/cells in red (error) or yellow (warning)
      - duplicate_suspects → show [Merge] / [Keep Both] buttons on grouped rows
      - yield_warnings → show a budget/capacity warning banner at the top
      - normalized_rows → populate the editable HitL data grid
    """
    event = await _get_event(event_id, current_user.tenant_id, db)
    event_categories = list((event.category_rules or {}).keys())
    rows = body.raw_rows

    # 1. Derive column classifications FROM the confirmed mapping — not heuristics.
    #    If Gemini said "Contact Number" → "phone", we know it's a phone column.
    #    This is always more accurate than guessing from the header name.
    PII_FIELDS = {"name", "email", "phone"}
    col_classifications: dict[str, str] = {}
    for m in body.confirmed_mapping:
        db_field = m.get("db_field", "skip")
        col_classifications[m["csv_column"]] = db_field if db_field in PII_FIELDS else "safe"

    # 2. Mask ALL rows using the mapping-derived classifications
    from app.core.etl.sanitizer import mask_row
    masked_rows = [mask_row(row, col_classifications) for row in rows]
    headers = list(rows[0].keys()) if rows else []

    # 3. Gemini Call 2 — full masked dataset
    try:
        ai_result: FullValidationResponse = await call2_validate_dataset(
            masked_rows=masked_rows,
            confirmed_mapping=body.confirmed_mapping,
            event_category_options=event_categories,
            column_classifications=col_classifications,
            category_rules=event.category_rules or {},
        )
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        logger.exception("Gemini Call 2 failed")
        raise HTTPException(status_code=502, detail=f"AI validation failed: {e}")

    # 3. Apply mapping to produce normalized rows for the HitL grid
    normalized = apply_mapping(rows, body.confirmed_mapping)

    # 4. Auto-apply Gemini's intelligent category suggestions!
    #    Since we removed the simplistic substring check, Gemini is the brain that maps
    #    "Head of Operations" -> "vip". If Gemini suggests a valid category, we update 
    #    the row and change the anomaly severity so the frontend knows it was Auto-Fixed.
    valid_cats_lower = [c.lower() for c in event_categories]
    for anomaly in ai_result.anomalies:
        if (
            anomaly.issue_type.lower() in ("category mismatch", "category_mismatch")
            and anomaly.suggested_fix.lower() in valid_cats_lower
            and 0 <= anomaly.row_index < len(normalized)
        ):
            # Apply Gemini's fix automatically
            normalized[anomaly.row_index]["category"] = anomaly.suggested_fix.lower()
            # Downgrade severity so the UI can show this as a helpful green "Auto-fixed by AI"
            anomaly.severity = "Info (Auto-Fixed)"

    # 5. Yield warnings (cross-check room inventory)
    inventory = await _get_room_inventory(event_id, db)
    yield_warnings = check_yield_warnings(normalized, inventory)

    return ValidationReport(
        anomalies=[a.model_dump() for a in ai_result.anomalies],
        duplicate_suspects=[d.model_dump() for d in ai_result.duplicate_suspects],
        yield_warnings=yield_warnings,
        total_rows=ai_result.total_rows_analyzed,
        clean_rows_estimate=ai_result.clean_rows_count,
        summary=ai_result.summary,
        normalized_rows=normalized,
    )


# ---------------------------------------------------------------------------
# STAGE 3: Commit — Final validation + bulk DB insert
# ---------------------------------------------------------------------------


@router.post(
    "/events/{event_id}/import/commit",
    response_model=CommitResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Stage 3: Planner approves HitL grid → bulk insert to database",
)
async def commit_import(
    event_id: uuid.UUID,
    body: CommitRequest,
    current_user: User = Depends(require_role(["admin", "planner"])),
    db: AsyncSession = Depends(get_db),
):
    """
    Takes the planner's final approval: normalized rows + any inline corrections
    made in the HitL grid, runs one last deterministic validation,
    and bulk-inserts clean guests into the database.

    Magic links and invitation emails are dispatched asynchronously via Celery.
    Duplicate emails (vs existing DB records) are skipped, not failed.

    Frontend connects to:
      - created → show success toast "245 guests imported successfully!"
      - skipped → show grey info "14 rows skipped (duplicates)"
      - errors → show collapsible error log for rows that still failed
      - yield_warnings → show reminder about waitlisted guests
    """
    event = await _get_event(event_id, current_user.tenant_id, db)
    event_categories = list((event.category_rules or {}).keys())

    # 1. Apply planner corrections from the HitL grid
    rows = apply_planner_corrections(
        body.normalized_rows,
        [c.model_dump() for c in body.corrections],
    )

    # 2. Pre-load existing emails to enforce skip-duplicate rule
    existing_result = await db.execute(
        select(Guest.email).where(
            Guest.event_id == event_id,
            Guest.is_active == True,  # noqa: E712
            Guest.email.isnot(None),
        )
    )
    existing_emails: set[str] = {r[0].lower() for r in existing_result.all() if r[0]}

    # 3. Final deterministic validation
    clean_rows, error_rows = validate_and_clean(rows, event_categories, existing_emails)

    # 4. Yield warnings (recalculate on the final clean set)
    inventory = await _get_room_inventory(event_id, db)
    yield_warnings = check_yield_warnings(clean_rows, inventory)

    if not clean_rows:
        raise HTTPException(
            status_code=422,
            detail={
                "message": "No valid rows to import after final validation.",
                "errors": [r["_errors"] for r in error_rows],
            },
        )

    # 5. Delegate to existing GuestBulkCreate service
    guest_payloads = [
        GuestBulkCreateItem(
            name=r["name"],
            email=r.get("email"),
            phone=r.get("phone"),
            category=r["category"],
            dietary_requirements=r.get("dietary_requirements") or {},
            extra_data=r.get("extra_data") or {},
        )
        for r in clean_rows
    ]

    result = await bulk_create_guests(
        data=GuestBulkCreate(guests=guest_payloads),
        tenant_id=current_user.tenant_id,
        event_id=event_id,
        db=db,
    )

    # Merge final validation errors with bulk_create skips
    all_errors = list(result.errors)
    for row in error_rows:
        all_errors.append(f"Row {row.get('_row_index')}: {'; '.join(row.get('_errors', []))}")

    return CommitResponse(
        created=result.created,
        skipped=result.skipped + len(error_rows),
        errors=all_errors,
        yield_warnings=yield_warnings,
    )
