"""
Eventflow API — Full Automated Test Suite
Run: pip install httpx && python test_eventflow.py
Tests every endpoint in chronological order and prints PASS/FAIL for each step.
"""

import asyncio
import httpx
import json
import sys
from datetime import datetime

BASE = "http://localhost:8000"
PASS = "\033[92m  PASS\033[0m"
FAIL = "\033[91m  FAIL\033[0m"
INFO = "\033[94m  INFO\033[0m"
WARN = "\033[93m  WARN\033[0m"

# Shared state — filled in as tests run
state = {}


def log(symbol, step, msg, extra=None):
    print(f"{symbol}  [{step}] {msg}")
    if extra:
        print(f"         {extra}")


def assert_status(resp, expected, step, label):
    if resp.status_code == expected:
        log(PASS, step, label, f"HTTP {resp.status_code}")
        return True
    else:
        log(FAIL, step, label, f"Expected {expected}, got {resp.status_code} — {resp.text[:200]}")
        return False


def assert_field(data, field, expected_value, step, label):
    actual = data.get(field)
    if actual == expected_value:
        log(PASS, step, f"{label} — {field} == {repr(expected_value)}")
        return True
    else:
        log(FAIL, step, f"{label} — {field}", f"Expected {repr(expected_value)}, got {repr(actual)}")
        return False


def assert_field_exists(data, field, step, label):
    if data.get(field):
        log(PASS, step, f"{label} — {field} present", str(data[field])[:80])
        return True
    else:
        log(FAIL, step, f"{label} — {field} MISSING or null", str(data))
        return False


async def run():
    fails = 0
    async with httpx.AsyncClient(base_url=BASE, timeout=15) as client:

        print("\n" + "="*60)
        print("  EVENTFLOW API TEST SUITE")
        print(f"  {BASE}")
        print("="*60)

        # ── HEALTH CHECK ──────────────────────────────────────────────
        print("\n── System ──────────────────────────────────────────────")
        resp = await client.get("/health")
        if not assert_status(resp, 200, "S1", "Health check"): fails += 1

        # ── AUTH ──────────────────────────────────────────────────────
        print("\n── Auth ─────────────────────────────────────────────────")

        # Register
        resp = await client.post("/api/v1/auth/register", json={
            "tenant_name": "Test Events LLC",
            "tenant_type": "corporate",
            "name": "Test Planner",
            "email": "planner@testevents.com",
            "password": "Password123!"
        })
        if not assert_status(resp, 201, "A1", "Register tenant + admin"): fails += 1
        else:
            data = resp.json()
            state["access_token"] = data.get("access_token")
            state["refresh_token"] = data.get("refresh_token")
            if not assert_field_exists(data, "access_token", "A1", "Register"): fails += 1
            if not assert_field_exists(data, "refresh_token", "A1", "Register"): fails += 1

        headers = {"Authorization": f"Bearer {state.get('access_token', '')}"}

        # Login
        resp = await client.post("/api/v1/auth/login", json={
            "email": "planner@testevents.com",
            "password": "Password123!"
        })
        if not assert_status(resp, 200, "A2", "Login"): fails += 1
        else:
            data = resp.json()
            state["access_token"] = data.get("access_token")
            state["refresh_token"] = data.get("refresh_token")
            headers = {"Authorization": f"Bearer {state['access_token']}"}
            log(INFO, "A2", "Token refreshed from login")

        # Refresh token
        resp = await client.post("/api/v1/auth/refresh", json={
            "refresh_token": state.get("refresh_token", "")
        })
        if not assert_status(resp, 200, "A3", "Refresh token"): fails += 1
        else:
            state["access_token"] = resp.json().get("access_token")
            headers = {"Authorization": f"Bearer {state['access_token']}"}

        # Login with wrong password
        resp = await client.post("/api/v1/auth/login", json={
            "email": "planner@testevents.com",
            "password": "WrongPassword!"
        })
        if resp.status_code in (400, 401, 422):
            log(PASS, "A4", "Login wrong password — correctly rejected", f"HTTP {resp.status_code}")
        else:
            log(FAIL, "A4", "Login wrong password — should have been rejected", f"HTTP {resp.status_code}")
            fails += 1

        # Get /me
        resp = await client.get("/api/v1/auth/me", headers=headers)
        if not assert_status(resp, 200, "A5", "GET /me"): fails += 1
        else:
            data = resp.json()
            if not assert_field(data, "role", "admin", "A5", "GET /me"): fails += 1
            if not assert_field(data, "is_active", True, "A5", "GET /me"): fails += 1
            state["user_id"] = data.get("id")
            state["tenant_id"] = data.get("tenant_id")

        # GET /me with no token
        resp = await client.get("/api/v1/auth/me")
        if resp.status_code in (401, 403):
            log(PASS, "A6", "GET /me no token — correctly rejected", f"HTTP {resp.status_code}")
        else:
            log(FAIL, "A6", "GET /me no token — should be 401/403", f"HTTP {resp.status_code}")
            fails += 1

        # ── VENUES ───────────────────────────────────────────────────
        print("\n── Venues ───────────────────────────────────────────────")

        resp = await client.post("/api/v1/venues", headers=headers, json={
            "name": "The Grand Plaza Hotel",
            "city": "Goa",
            "state": "Goa",
            "total_rooms": 200,
            "contact_email": "hello@grandplaza.com"
        })
        if not assert_status(resp, 201, "V1", "Create venue"): fails += 1
        else:
            data = resp.json()
            state["venue_id"] = data.get("id")
            if not assert_field_exists(data, "id", "V1", "Create venue"): fails += 1
            if not assert_field(data, "is_active", True, "V1", "Create venue"): fails += 1

        # Create second venue for filter test
        resp = await client.post("/api/v1/venues", headers=headers, json={
            "name": "Mumbai Convention Centre",
            "city": "Mumbai",
            "state": "Maharashtra",
            "total_rooms": 500,
        })
        if not assert_status(resp, 201, "V2", "Create second venue (Mumbai)"): fails += 1

        # List venues no filter
        resp = await client.get("/api/v1/venues", headers=headers)
        if not assert_status(resp, 200, "V3", "List venues — no filter"): fails += 1
        else:
            data = resp.json()
            if data.get("total", 0) >= 2:
                log(PASS, "V3", "List venues — total >= 2", f"total={data['total']}")
            else:
                log(FAIL, "V3", "List venues — expected >= 2", f"total={data.get('total')}")
                fails += 1

        # List venues filter by city
        resp = await client.get("/api/v1/venues?city=Goa", headers=headers)
        if not assert_status(resp, 200, "V4", "List venues — city=Goa filter"): fails += 1
        else:
            venues = resp.json().get("venues", [])
            if all(v["city"] == "Goa" for v in venues):
                log(PASS, "V4", "City filter correct — all results are Goa")
            else:
                log(FAIL, "V4", "City filter returned non-Goa venues")
                fails += 1

        # Get venue by ID
        resp = await client.get(f"/api/v1/venues/{state['venue_id']}", headers=headers)
        if not assert_status(resp, 200, "V5", "Get venue by ID"): fails += 1

        # Get venue — invalid UUID
        resp = await client.get("/api/v1/venues/not-a-uuid", headers=headers)
        if resp.status_code == 422:
            log(PASS, "V6", "Get venue invalid UUID — correctly 422")
        else:
            log(FAIL, "V6", "Get venue invalid UUID — expected 422", f"HTTP {resp.status_code}")
            fails += 1

        # ── EVENTS ───────────────────────────────────────────────────
        print("\n── Events ───────────────────────────────────────────────")

        resp = await client.post("/api/v1/events", headers=headers, json={
            "name": "Annual Tech Conference 2026",
            "type": "conference",
            "start_date": "2026-05-01",
            "end_date": "2026-05-03",
            "expected_guests": 200,
            "destination": "Goa",
            "description": "3-day conference",
            "category_rules": {
                "employee": {"allowed_room_types": ["standard"], "subsidy_per_night": 8000},
                "vip": {"allowed_room_types": ["deluxe", "suite"], "subsidy_per_night": 15000}
            }
        })
        if not assert_status(resp, 201, "E1", "Create event"): fails += 1
        else:
            data = resp.json()
            state["event_id"] = data.get("id")
            if not assert_field(data, "status", "draft", "E1", "Create event"): fails += 1

        # Invalid event type
        resp = await client.post("/api/v1/events", headers=headers, json={
            "name": "Bad Event",
            "type": "festival",
            "start_date": "2026-05-01",
            "end_date": "2026-05-03"
        })
        if resp.status_code == 422:
            log(PASS, "E2", "Invalid event type — correctly 422")
        else:
            log(FAIL, "E2", "Invalid event type — expected 422", f"HTTP {resp.status_code}")
            fails += 1

        # List events
        resp = await client.get("/api/v1/events", headers=headers)
        if not assert_status(resp, 200, "E3", "List events"): fails += 1

        # Get event by ID
        resp = await client.get(f"/api/v1/events/{state['event_id']}", headers=headers)
        if not assert_status(resp, 200, "E4", "Get event by ID"): fails += 1

        # Update event status to active
        resp = await client.put(f"/api/v1/events/{state['event_id']}", headers=headers, json={
            "status": "active",
            "expected_guests": 300
        })
        if not assert_status(resp, 200, "E5", "Update event status to active"): fails += 1
        else:
            if not assert_field(resp.json(), "status", "active", "E5", "Update event"): fails += 1

        # Invalid status value
        resp = await client.put(f"/api/v1/events/{state['event_id']}", headers=headers, json={
            "status": "running"
        })
        if resp.status_code == 422:
            log(PASS, "E6", "Invalid status value — correctly 422")
        else:
            log(FAIL, "E6", "Invalid status value — expected 422", f"HTTP {resp.status_code}")
            fails += 1

        # ── GUESTS ───────────────────────────────────────────────────
        print("\n── Guests ───────────────────────────────────────────────")
        eid = state["event_id"]

        # Create Guest 1 — Bruce Wayne (VIP)
        resp = await client.post(f"/api/v1/events/{eid}/guests", headers=headers, json={
            "name": "Bruce Wayne",
            "email": "bruce@wayne.com",
            "phone": "+1234567890",
            "category": "vip",
            "dietary_requirements": {"vegetarian": False},
            "extra_data": {"department": "Executive"}
        })
        if not assert_status(resp, 201, "G1", "Create guest 1 — Bruce Wayne"): fails += 1
        else:
            data = resp.json()
            state["guest_1_id"] = data.get("id")
            state["guest_1_token"] = data.get("booking_token")
            if not assert_field(data, "is_active", True, "G1", "Bruce active"): fails += 1
            if not assert_field_exists(data, "booking_token", "G1", "Bruce token"): fails += 1

        # Create Guest 2 — Clark Kent (employee)
        resp = await client.post(f"/api/v1/events/{eid}/guests", headers=headers, json={
            "name": "Clark Kent",
            "email": "clark@dailyplanet.com",
            "phone": "+9876543210",
            "category": "employee",
            "dietary_requirements": {"vegetarian": True},
            "extra_data": {"department": "Reporting"}
        })
        if not assert_status(resp, 201, "G2", "Create guest 2 — Clark Kent"): fails += 1
        else:
            data = resp.json()
            state["guest_2_id"] = data.get("id")
            state["guest_2_token"] = data.get("booking_token")
            if not assert_field_exists(data, "booking_token", "G2", "Clark token"): fails += 1

        # Duplicate email — should fail
        resp = await client.post(f"/api/v1/events/{eid}/guests", headers=headers, json={
            "name": "Bruce Wayne Duplicate",
            "email": "bruce@wayne.com",
            "category": "vip"
        })
        if resp.status_code in (409, 422, 400):
            log(PASS, "G3", "Duplicate email — correctly rejected", f"HTTP {resp.status_code}")
        else:
            log(FAIL, "G3", "Duplicate email — should be rejected", f"HTTP {resp.status_code}")
            fails += 1

        # Bulk import
        resp = await client.post(f"/api/v1/events/{eid}/guests/bulk", headers=headers, json={
            "guests": [
                {"name": "Diana Prince", "email": "diana@themyscira.com", "category": "vip"},
                {"name": "Barry Allen", "email": "barry@centralcity.com", "category": "employee"},
                {"name": "X", "email": "invalid-email", "category": "employee"}
            ]
        })
        if not assert_status(resp, 201, "G4", "Bulk import guests"): fails += 1
        else:
            data = resp.json()
            state["guest_3_id"] = data.get("guests", [{}])[0].get("id")
            if data.get("created") == 2:
                log(PASS, "G4", "Bulk import — created=2 correct")
            else:
                log(FAIL, "G4", "Bulk import — expected created=2", f"created={data.get('created')}")
                fails += 1
            if data.get("skipped") == 1:
                log(PASS, "G4", "Bulk import — skipped=1 correct")
            else:
                log(FAIL, "G4", "Bulk import — expected skipped=1", f"skipped={data.get('skipped')}")
                fails += 1

        # List guests
        resp = await client.get(f"/api/v1/events/{eid}/guests", headers=headers)
        if not assert_status(resp, 200, "G5", "List guests"): fails += 1

        # Filter by category
        resp = await client.get(f"/api/v1/events/{eid}/guests?category=vip", headers=headers)
        if not assert_status(resp, 200, "G6", "List guests — category=vip filter"): fails += 1
        else:
            guests = resp.json().get("guests", [])
            if all(g["category"] == "vip" for g in guests):
                log(PASS, "G6", "Category filter correct — all vip")
            else:
                log(FAIL, "G6", "Category filter returned non-vip guests")
                fails += 1

        # Get single guest
        resp = await client.get(f"/api/v1/events/{eid}/guests/{state['guest_1_id']}", headers=headers)
        if not assert_status(resp, 200, "G7", "Get guest by ID"): fails += 1

        # Update guest
        resp = await client.put(f"/api/v1/events/{eid}/guests/{state['guest_2_id']}", headers=headers, json={
            "phone": "+1111111111",
            "dietary_requirements": {"vegetarian": True, "gluten_free": True}
        })
        if not assert_status(resp, 200, "G8", "Update guest — Clark"): fails += 1

        # Deactivate Diana (guest_3) — not Bruce or Clark
        if state.get("guest_3_id"):
            resp = await client.delete(f"/api/v1/events/{eid}/guests/{state['guest_3_id']}", headers=headers)
            if not assert_status(resp, 200, "G9", "Deactivate guest — Diana"): fails += 1
            else:
                if not assert_field(resp.json(), "is_active", False, "G9", "Diana deactivated"): fails += 1

            # Verify Diana hidden from active list
            resp = await client.get(f"/api/v1/events/{eid}/guests?active_only=true", headers=headers)
            if not assert_status(resp, 200, "G10", "List active guests — Diana excluded"): fails += 1
            else:
                ids = [g["id"] for g in resp.json().get("guests", [])]
                if state["guest_3_id"] not in ids:
                    log(PASS, "G10", "Diana not in active guest list")
                else:
                    log(FAIL, "G10", "Diana still showing in active list")
                    fails += 1

            # Verify Diana visible with active_only=false
            resp = await client.get(f"/api/v1/events/{eid}/guests?active_only=false", headers=headers)
            if not assert_status(resp, 200, "G11", "List all guests — Diana included"): fails += 1
            else:
                ids = [g["id"] for g in resp.json().get("guests", [])]
                if state["guest_3_id"] in ids:
                    log(PASS, "G11", "Diana visible with active_only=false")
                else:
                    log(FAIL, "G11", "Diana missing from full guest list")
                    fails += 1

        # ── ROOM BLOCKS ──────────────────────────────────────────────
        print("\n── Room Blocks ──────────────────────────────────────────")

        resp = await client.post(f"/api/v1/events/{eid}/room-blocks", headers=headers, json={
            "venue_id": state["venue_id"],
            "check_in_date": "2026-05-01",
            "check_out_date": "2026-05-03",
            "hold_deadline": "2026-04-15",
            "notes": "Test block — 1 standard room only",
            "allotments": [
                {"room_type": "standard", "total_rooms": 1, "negotiated_rate": 8500.00},
                {"room_type": "deluxe", "total_rooms": 5, "negotiated_rate": 15000.00}
            ]
        })
        if not assert_status(resp, 201, "B1", "Create room block"): fails += 1
        else:
            data = resp.json()
            state["block_id"] = data.get("id")
            if not assert_field(data, "status", "confirmed", "B1", "Block status"): fails += 1
            allotments = data.get("allotments", [])
            std = next((a for a in allotments if a["room_type"] == "standard"), None)
            if std and std["booked_rooms"] == 0 and std["held_rooms"] == 0:
                log(PASS, "B1", "Allotment counters start at 0")
            else:
                log(FAIL, "B1", "Allotment counters not zeroed", str(std))
                fails += 1

        # List room blocks
        resp = await client.get(f"/api/v1/events/{eid}/room-blocks", headers=headers)
        if not assert_status(resp, 200, "B2", "List room blocks"): fails += 1

        # Get single room block
        resp = await client.get(f"/api/v1/room-blocks/{state['block_id']}", headers=headers)
        if not assert_status(resp, 200, "B3", "Get room block by ID"): fails += 1

        # Update room block metadata
        resp = await client.put(f"/api/v1/room-blocks/{state['block_id']}", headers=headers, json={
            "hold_deadline": "2026-04-20",
            "notes": "Extended deadline"
        })
        if not assert_status(resp, 200, "B4", "Update room block metadata"): fails += 1

        # ── BOOKING ENGINE ───────────────────────────────────────────
        print("\n── Booking Engine ───────────────────────────────────────")

        # Bruce holds
        resp = await client.post("/api/v1/public/hold", json={
            "guest_token": state["guest_1_token"],
            "room_block_id": state["block_id"],
            "room_type": "standard"
        })
        if not assert_status(resp, 201, "BK1", "Bruce places hold"): fails += 1
        else:
            data = resp.json()
            state["booking_id"] = data.get("id")
            if not assert_field(data, "status", "HELD", "BK1", "Hold status"): fails += 1
            if not assert_field_exists(data, "hold_expires_at", "BK1", "Hold timer"): fails += 1

        # Verify allotment held_rooms = 1
        resp = await client.get(f"/api/v1/room-blocks/{state['block_id']}", headers=headers)
        if resp.status_code == 200:
            allotments = resp.json().get("allotments", [])
            std = next((a for a in allotments if a["room_type"] == "standard"), None)
            if std and std["held_rooms"] == 1:
                log(PASS, "BK1b", "held_rooms incremented to 1")
            else:
                log(FAIL, "BK1b", "held_rooms not incremented", str(std))
                fails += 1

        # Bruce tries to hold again — should fail
        resp = await client.post("/api/v1/public/hold", json={
            "guest_token": state["guest_1_token"],
            "room_block_id": state["block_id"],
            "room_type": "standard"
        })
        if resp.status_code == 409:
            log(PASS, "BK2", "Double hold prevented — correctly 409")
        else:
            log(FAIL, "BK2", "Double hold — expected 409", f"HTTP {resp.status_code}")
            fails += 1

        # Confirm Bruce's booking
        resp = await client.post(f"/api/v1/public/webhooks/razorpay/{state['booking_id']}/confirm", json={
            "payment_reference": "pay_TEST123ABC"
        })
        if not assert_status(resp, 200, "BK3", "Confirm Bruce's booking"): fails += 1
        else:
            if not assert_field(resp.json(), "status", "CONFIRMED", "BK3", "Booking confirmed"): fails += 1

        # Verify allotment: held_rooms=0, booked_rooms=1
        resp = await client.get(f"/api/v1/room-blocks/{state['block_id']}", headers=headers)
        if resp.status_code == 200:
            allotments = resp.json().get("allotments", [])
            std = next((a for a in allotments if a["room_type"] == "standard"), None)
            if std and std["held_rooms"] == 0 and std["booked_rooms"] == 1:
                log(PASS, "BK3b", "Allotment: held_rooms=0, booked_rooms=1")
            else:
                log(FAIL, "BK3b", "Allotment counters wrong after confirm", str(std))
                fails += 1

        # Clark tries to hold — must get 409
        resp = await client.post("/api/v1/public/hold", json={
            "guest_token": state["guest_2_token"],
            "room_block_id": state["block_id"],
            "room_type": "standard"
        })
        if resp.status_code == 409:
            log(PASS, "BK4", "Clark rejected — room fully booked 409")
        else:
            log(FAIL, "BK4", "Clark should get 409 — room full", f"HTTP {resp.status_code} — {resp.text[:200]}")
            fails += 1

        # List bookings
        resp = await client.get(f"/api/v1/events/{eid}/bookings", headers=headers)
        if not assert_status(resp, 200, "BK5", "List bookings for event"): fails += 1
        else:
            items = resp.json().get("items", [])
            confirmed = [b for b in items if b["status"] == "CONFIRMED"]
            if confirmed:
                log(PASS, "BK5", "CONFIRMED booking visible in list")
            else:
                log(FAIL, "BK5", "No CONFIRMED booking in list")
                fails += 1

        # ── WAITLIST ─────────────────────────────────────────────────
        print("\n── Waitlist ─────────────────────────────────────────────")

        # Clark joins waitlist
        resp = await client.post(f"/api/v1/events/{eid}/waitlist", headers=headers, json={
            "guest_id": state["guest_2_id"],
            "room_block_id": state["block_id"],
            "room_type": "standard"
        })
        if not assert_status(resp, 201, "W1", "Clark joins waitlist"): fails += 1
        else:
            data = resp.json()
            state["waitlist_id"] = data.get("id")
            if not assert_field(data, "status", "waiting", "W1", "Waitlist status"): fails += 1
            if data.get("position") == 1:
                log(PASS, "W1", "Clark at position 1")
            else:
                log(FAIL, "W1", "Clark not at position 1", f"position={data.get('position')}")
                fails += 1

        # List waitlist
        resp = await client.get(f"/api/v1/events/{eid}/waitlist", headers=headers)
        if not assert_status(resp, 200, "W2", "List waitlist"): fails += 1
        else:
            items = resp.json().get("items", [])
            clark_entry = next((i for i in items if i["guest_id"] == state["guest_2_id"]), None)
            if clark_entry and clark_entry["status"] == "waiting":
                log(PASS, "W2", "Clark confirmed waiting in list")
            else:
                log(FAIL, "W2", "Clark not found waiting in waitlist", str(items))
                fails += 1

        # THE GRAND FINALE — Bruce cancels
        resp = await client.delete(f"/api/v1/bookings/{state['booking_id']}", headers=headers)
        if not assert_status(resp, 200, "W3", "Bruce cancels booking"): fails += 1
        else:
            if not assert_field(resp.json(), "status", "CANCELLED", "W3", "Booking cancelled"): fails += 1

        # Verify allotment: booked_rooms back to 0
        resp = await client.get(f"/api/v1/room-blocks/{state['block_id']}", headers=headers)
        if resp.status_code == 200:
            allotments = resp.json().get("allotments", [])
            std = next((a for a in allotments if a["room_type"] == "standard"), None)
            if std and std["booked_rooms"] == 0:
                log(PASS, "W3b", "booked_rooms back to 0 after cancel")
            else:
                log(FAIL, "W3b", "booked_rooms not decremented", str(std))
                fails += 1

        # KEY TEST — Clark must now be "offered"
        resp = await client.get(f"/api/v1/events/{eid}/waitlist", headers=headers)
        if not assert_status(resp, 200, "W4", "Waitlist after cancel — check Clark promoted"): fails += 1
        else:
            items = resp.json().get("items", [])
            clark_entry = next((i for i in items if i["guest_id"] == state["guest_2_id"]), None)
            if clark_entry and clark_entry["status"] == "offered":
                log(PASS, "W4", "Clark auto-promoted to OFFERED")
                if clark_entry.get("offer_expires_at"):
                    log(PASS, "W4", "offer_expires_at set", clark_entry["offer_expires_at"])
                else:
                    log(FAIL, "W4", "offer_expires_at is null after promotion")
                    fails += 1
            else:
                log(FAIL, "W4", "Clark NOT promoted — still waiting or missing",
                    f"status={clark_entry.get('status') if clark_entry else 'NOT FOUND'}")
                fails += 1

        # Clark now holds using his token (room is free again)
        resp = await client.post("/api/v1/public/hold", json={
            "guest_token": state["guest_2_token"],
            "room_block_id": state["block_id"],
            "room_type": "standard"
        })
        if not assert_status(resp, 201, "W5", "Clark holds after promotion"): fails += 1
        else:
            state["clark_booking_id"] = resp.json().get("id")
            if not assert_field(resp.json(), "status", "HELD", "W5", "Clark HELD"): fails += 1

        # Clark confirms
        if state.get("clark_booking_id"):
            resp = await client.post(
                f"/api/v1/public/webhooks/razorpay/{state['clark_booking_id']}/confirm",
                json={"payment_reference": "pay_CLARK999"}
            )
            if not assert_status(resp, 200, "W6", "Clark confirms booking"): fails += 1
            else:
                if not assert_field(resp.json(), "status", "CONFIRMED", "W6", "Clark CONFIRMED"): fails += 1

        # Manually update waitlist status
        if state.get("waitlist_id"):
            resp = await client.put(f"/api/v1/waitlists/{state['waitlist_id']}/status", headers=headers, json={
                "status": "expired"
            })
            if not assert_status(resp, 200, "W7", "Manual waitlist status update"): fails += 1

            # Invalid status
            resp = await client.put(f"/api/v1/waitlists/{state['waitlist_id']}/status", headers=headers, json={
                "status": "removed"
            })
            if resp.status_code == 422:
                log(PASS, "W8", "Invalid waitlist status — correctly 422")
            else:
                log(FAIL, "W8", "Invalid waitlist status — expected 422", f"HTTP {resp.status_code}")
                fails += 1

        # ── SUMMARY ──────────────────────────────────────────────────
        print("\n" + "="*60)
        if fails == 0:
            print(f"\033[92m  ALL TESTS PASSED\033[0m")
        else:
            print(f"\033[91m  {fails} TEST(S) FAILED — check output above\033[0m")
        print("="*60 + "\n")

        return fails


if __name__ == "__main__":
    result = asyncio.run(run())
    sys.exit(0 if result == 0 else 1)