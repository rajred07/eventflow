"""
Interactive ETL Pipeline Tester
================================
Run: uv run python test_etl_interactive.py

This script walks through all 3 ETL stages interactively, printing every
input/output so you can see exactly what's happening at each step.

Requirements: uvicorn must be running on port 8000
              You need a valid event_id (run setup_demo.py first)
"""

import json
import os
import sys
import requests

BASE_URL = "http://localhost:8000/api/v1"
CSV_FILE = "test_import.csv"

# ─── ANSI colors ──────────────────────────────────────────────────────────────
BOLD   = "\033[1m"
RESET  = "\033[0m"
GREEN  = "\033[92m"
YELLOW = "\033[93m"
RED    = "\033[91m"
CYAN   = "\033[96m"
BLUE   = "\033[94m"
GREY   = "\033[90m"
MAGENTA= "\033[95m"

def hdr(title: str):
    print(f"\n{BOLD}{CYAN}{'═'*60}{RESET}")
    print(f"{BOLD}{CYAN}  {title}{RESET}")
    print(f"{BOLD}{CYAN}{'═'*60}{RESET}\n")

def ok(msg: str):    print(f"  {GREEN}✓  {msg}{RESET}")
def warn(msg: str):  print(f"  {YELLOW}⚠  {msg}{RESET}")
def err(msg: str):   print(f"  {RED}✗  {msg}{RESET}")
def info(msg: str):  print(f"  {BLUE}ℹ  {msg}{RESET}")
def debug(msg: str): print(f"  {GREY}{msg}{RESET}")
def step(n, msg: str): print(f"\n{BOLD}{MAGENTA}Step {n}:{RESET} {msg}")


def login(email: str, password: str) -> str:
    """Login and return JWT token."""
    r = requests.post(f"{BASE_URL}/auth/login", json={"email": email, "password": password})
    if r.status_code != 200:
        err(f"Login failed: {r.text}")
        sys.exit(1)
    token = r.json()["access_token"]
    ok(f"Logged in as {email}")
    return token


def get_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# ─── STAGE 1 ──────────────────────────────────────────────────────────────────

def stage1_analyze(token: str, event_id: str) -> tuple[dict, list[dict]]:
    hdr("STAGE 1 — Upload CSV → Gemini Schema Mapping (Call 1)")

    if not os.path.exists(CSV_FILE):
        err(f"CSV file '{CSV_FILE}' not found. Run from the backend directory.")
        sys.exit(1)

    # Parse raw rows ourselves so we can show them + send to Stage 2
    import csv, io
    with open(CSV_FILE, encoding="utf-8") as f:
        raw_text = f.read()

    reader = csv.DictReader(io.StringIO(raw_text))
    raw_rows = []
    for row in reader:
        # Convert empty strings to None to match what pandas does
        raw_rows.append({k: (v if v.strip() != "" else None) for k, v in row.items()})

    step(1, f"Uploading '{CSV_FILE}' ({len(raw_rows)} rows) to /import/analyze ...")

    with open(CSV_FILE, "rb") as f:
        r = requests.post(
            f"{BASE_URL}/events/{event_id}/import/analyze",
            headers=get_headers(token),
            files={"file": (CSV_FILE, f, "text/csv")},
        )

    if r.status_code != 200:
        err(f"Stage 1 failed [{r.status_code}]: {r.text[:500]}")
        sys.exit(1)

    result = r.json()

    step(2, "Gemini's Column Mapping Proposal:")
    print(f"\n  {'CSV Column':<30} {'DB Field':<25} {'Conf':>6}  Reason")
    print(f"  {'─'*30} {'─'*25} {'─'*6}  {'─'*35}")
    for m in result["proposed_mapping"]:
        conf_color = GREEN if m["confidence"] >= 0.9 else YELLOW if m["confidence"] >= 0.7 else RED
        field_color = CYAN if m["db_field"] not in ("skip", "extra_data") else GREY
        print(
            f"  {m['csv_column']:<30} "
            f"{field_color}{m['db_field']:<25}{RESET} "
            f"{conf_color}{m['confidence']:>6.2f}{RESET}  "
            f"{GREY}{m['reason'][:60]}{RESET}"
        )

    step(3, "PII Column Classifications (what gets masked before Gemini Call 2):")
    for col, kind in result["column_classifications"].items():
        if kind == "email":
            print(f"  {RED}[EMAIL]{RESET}  {col}")
        elif kind == "phone":
            print(f"  {YELLOW}[PHONE]{RESET}  {col}")
        elif kind == "name":
            print(f"  {MAGENTA}[NAME]{RESET}   {col}")
        else:
            print(f"  {GREY}[SAFE]{RESET}   {col}")

    if result.get("ai_notes"):
        step(4, "AI Notes:")
        print(f"  {CYAN}{result['ai_notes']}{RESET}")

    # Interactive: let user override the mapping
    print(f"\n  {BOLD}Event Categories:{RESET} {result['event_categories']}")
    print(f"  {BOLD}Total Rows:{RESET} {result['total_rows']}")

    confirmed_mapping = result["proposed_mapping"]

    print(f"\n{YELLOW}Do you want to override any column mapping? (y/n):{RESET}", end=" ")
    choice = input().strip().lower()
    if choice == "y":
        print(f"  Enter overrides as: csv_column=db_field  (e.g. 'Grade Level=category')")
        print(f"  Valid db_fields: name, email, phone, category, dietary_requirements, extra_data, skip")
        print(f"  Type 'done' when finished.\n")
        while True:
            override = input("  Override> ").strip()
            if override.lower() == "done":
                break
            if "=" in override:
                col, field = override.split("=", 1)
                col, field = col.strip(), field.strip()
                for m in confirmed_mapping:
                    if m["csv_column"] == col:
                        old = m["db_field"]
                        m["db_field"] = field
                        ok(f"Overrode: '{col}' → '{field}' (was '{old}')")
                        break
                else:
                    warn(f"Column '{col}' not found in mapping.")

    return confirmed_mapping, raw_rows


# ─── STAGE 2 ──────────────────────────────────────────────────────────────────

def stage2_validate(token: str, event_id: str, confirmed_mapping: list, raw_rows: list) -> tuple[dict, list]:
    hdr("STAGE 2 — Gemini Full Validation + PII Masking (Call 2)")

    # Show what gets masked
    step(1, "What the masked data looks like (first 3 rows):")
    pii_cols = {m["csv_column"]: m["db_field"] for m in confirmed_mapping if m["db_field"] in ("name", "email", "phone")}

    from app.core.etl.sanitizer import mask_row
    col_classifications = {}
    for m in confirmed_mapping:
        db_field = m.get("db_field", "skip")
        col_classifications[m["csv_column"]] = db_field if db_field in ("name", "email", "phone") else "safe"

    for i, row in enumerate(raw_rows[:3]):
        masked = mask_row(row, col_classifications)
        print(f"\n  {BOLD}Row {i} (ORIGINAL):{RESET}")
        for col, val in list(row.items())[:5]:
            print(f"    {col:<30}: {RED if col in pii_cols else GREY}{val}{RESET}")
        print(f"\n  {BOLD}Row {i} (MASKED → sent to Gemini):{RESET}")
        for col, val in list(masked.items())[:5]:
            if col in pii_cols:
                print(f"    {col:<30}: {GREEN}{val}{RESET}  {GREY}← masked{RESET}")
            else:
                print(f"    {col:<30}: {GREY}{val}{RESET}")

    step(2, f"Sending all {len(raw_rows)} rows (masked) to /import/validate ...")

    payload = {"confirmed_mapping": confirmed_mapping, "raw_rows": raw_rows}
    r = requests.post(
        f"{BASE_URL}/events/{event_id}/import/validate",
        headers={**get_headers(token), "Content-Type": "application/json"},
        json=payload,
    )

    if r.status_code != 200:
        err(f"Stage 2 failed [{r.status_code}]: {r.text[:800]}")
        sys.exit(1)

    result = r.json()

    step(3, f"AI Anomaly Report ({len(result['anomalies'])} issues found):")
    if not result["anomalies"]:
        ok("No anomalies found!")
    else:
        print(f"\n  {'Row':>4}  {'Severity':<10} {'Type':<25} {'Column':<25} {'Current':<25} Suggested Fix")
        print(f"  {'─'*4}  {'─'*10} {'─'*25} {'─'*25} {'─'*25} {'─'*30}")
        for a in result["anomalies"]:
            sev_color = RED if a["severity"].lower() in ("high","error") else YELLOW
            print(
                f"  {a['row_index']:>4}  "
                f"{sev_color}{a['severity']:<10}{RESET} "
                f"{a['issue_type']:<25} "
                f"{a['column']:<25} "
                f"{str(a['current_value']):<25} "
                f"{GREEN}{a['suggested_fix']}{RESET}"
            )

    step(4, f"Duplicate Suspects ({len(result['duplicate_suspects'])} groups):")
    if not result["duplicate_suspects"]:
        ok("No duplicates detected!")
    else:
        for d in result["duplicate_suspects"]:
            warn(f"Rows {d['row_indices']} — {d['reason']}")

    step(5, f"Yield Warnings ({len(result['yield_warnings'])} warnings):")
    if not result["yield_warnings"]:
        ok("No yield overflow — all guests fit within room inventory!")
    else:
        for w in result["yield_warnings"]:
            warn(w["message"])

    print(f"\n  {BOLD}Summary:{RESET} {CYAN}{result['summary']}{RESET}")
    print(f"  {BOLD}Total rows:{RESET} {result['total_rows']}  |  "
          f"{BOLD}Clean estimate:{RESET} {GREEN}{result['clean_rows_estimate']}{RESET}")

    # Show normalized_rows categories
    step(6, "Category normalization applied to normalized_rows:")
    cats = {}
    for row in result["normalized_rows"]:
        cat = row.get("category") or "NULL"
        cats[cat] = cats.get(cat, 0) + 1
    for cat, count in sorted(cats.items()):
        color = GREEN if cat in ("employee", "vip") else RED
        print(f"  {color}{cat}{RESET}: {count} rows")

    normalized_rows = result["normalized_rows"]

    # Interactive corrections
    print(f"\n{YELLOW}Do you want to make cell corrections before committing? (y/n):{RESET}", end=" ")
    corrections = []
    choice = input().strip().lower()
    if choice == "y":
        print(f"  Format: row_index,column,new_value  (e.g. '13,category,employee')")
        print(f"  Type 'done' when finished.\n")
        while True:
            correction = input("  Correction> ").strip()
            if correction.lower() == "done":
                break
            parts = correction.split(",", 2)
            if len(parts) == 3:
                try:
                    idx = int(parts[0])
                    col = parts[1].strip()
                    val = parts[2].strip()
                    corrections.append({"row_index": idx, "column": col, "new_value": val})
                    ok(f"Queued correction: row {idx}, {col} = '{val}'")
                    # Apply locally for display
                    if 0 <= idx < len(normalized_rows):
                        normalized_rows[idx][col] = val
                except ValueError:
                    warn("Invalid format. Use: row_index,column,new_value")
            else:
                warn("Invalid format. Use: row_index,column,new_value")

    return result, corrections


# ─── STAGE 3 ──────────────────────────────────────────────────────────────────

def stage3_commit(token: str, event_id: str, confirmed_mapping: list, validate_result: dict, corrections: list):
    hdr("STAGE 3 — Final Validation + Bulk DB Insert (Commit)")

    normalized_rows = validate_result["normalized_rows"]

    step(1, "Preview of what will be inserted (first 5 clean rows):")
    shown = 0
    for i, row in enumerate(normalized_rows):
        cat = (row.get("category") or "")
        email = (row.get("email") or "")
        if cat in ("employee", "vip") and "@" in email and "." in email:
            print(f"  {GREY}[{i:>2}]{RESET}  "
                  f"{BOLD}{row.get('name','?'):<25}{RESET}  "
                  f"{CYAN}{email:<30}{RESET}  "
                  f"{GREEN if cat=='vip' else BLUE}{cat}{RESET}")
            shown += 1
            if shown >= 5:
                break

    print(f"\n  {GREY}... {len(normalized_rows)} total normalized rows{RESET}")
    if corrections:
        print(f"  {YELLOW}{len(corrections)} planner correction(s) will be applied{RESET}")

    print(f"\n{YELLOW}Confirm and import all? ({GREEN}y{RESET}{YELLOW}/{RED}n{RESET}{YELLOW}):{RESET}", end=" ")
    choice = input().strip().lower()
    if choice != "y":
        warn("Import cancelled by user.")
        return

    step(2, "Sending commit request...")

    payload = {
        "confirmed_mapping": confirmed_mapping,
        "normalized_rows": normalized_rows,
        "corrections": corrections,
    }

    r = requests.post(
        f"{BASE_URL}/events/{event_id}/import/commit",
        headers={**get_headers(token), "Content-Type": "application/json"},
        json=payload,
    )

    if r.status_code not in (200, 201):
        err(f"Stage 3 failed [{r.status_code}]:")
        try:
            print(f"  {RED}{json.dumps(r.json(), indent=4)}{RESET}")
        except Exception:
            print(f"  {RED}{r.text[:800]}{RESET}")
        return

    result = r.json()

    step(3, "Import Result:")
    print(f"\n  {BOLD}{GREEN}✓ Created:{RESET}  {GREEN}{result['created']} guests{RESET}")
    print(f"  {BOLD}{GREY}  Skipped:{RESET}  {GREY}{result['skipped']} rows{RESET}")

    if result["errors"]:
        print(f"\n  {RED}Errors ({len(result['errors'])}):{RESET}")
        for e in result["errors"]:
            print(f"    {RED}• {e}{RESET}")

    if result.get("yield_warnings"):
        print(f"\n  {YELLOW}Yield Warnings:{RESET}")
        for w in result["yield_warnings"]:
            warn(w["message"])

    print()
    ok(f"ETL Pipeline complete! {result['created']} guests imported to event {event_id}")


# ─── MAIN ─────────────────────────────────────────────────────────────────────

def main():
    hdr("Eventflow ETL Interactive Tester")

    print(f"{BOLD}Configuration:{RESET}")
    print(f"  API:      {BASE_URL}")
    print(f"  CSV File: {CSV_FILE}")

    # Credentials
    print(f"\n{YELLOW}Enter planner email [{GREY}admin@eventflow.com{YELLOW}]:{RESET}", end=" ")
    email = input().strip() or "admin@eventflow.com"
    print(f"{YELLOW}Enter password [{GREY}password123{YELLOW}]:{RESET}", end=" ")
    password = input().strip() or "password123"

    token = login(email, password)

    # Event ID
    print(f"\n{YELLOW}Enter event_id (from setup_demo.py output or Swagger):{RESET}", end=" ")
    event_id = input().strip()
    if not event_id:
        err("Event ID is required.")
        sys.exit(1)

    # Run the pipeline
    confirmed_mapping, raw_rows = stage1_analyze(token, event_id)
    validate_result, corrections = stage2_validate(token, event_id, confirmed_mapping, raw_rows)
    stage3_commit(token, event_id, confirmed_mapping, validate_result, corrections)


if __name__ == "__main__":
    # Make sure we can import app modules (for the sanitizer in stage 2 preview)
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    main()
