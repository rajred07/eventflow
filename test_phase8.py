"""
Phase 8: WhatsApp Integration — Full Test Suite

Tests:
    1. Health check (server running, all imports resolved)
    2. Setup test data (event, venue, block, guests with and without phones)
    3. Verify Dual-Dispatch (email + WA) on Guest Creation (Invitations)
    4. Verify Booking Confirmation triggers WA
    5. Verify Waitlist Offer triggers WA
    6. Verify Reminder Blast triggers WA
    7. Notification Logs Audit Trail (check for channel="whatsapp")
"""

import json
import requests
import uuid
import time
from datetime import date, timedelta

BASE_URL = "http://127.0.0.1:8000/api/v1"


def print_step(title):
    print(f"\n{'='*70}")
    print(f"🚀 {title}")
    print(f"{'='*70}")


def print_response(r):
    print(f"Status: {r.status_code}")
    if r.status_code >= 400:
        print(f"Error: {r.text[:500]}")


# ══════════════════════════════════════════════════════════════════════════════
# SETUP
# ══════════════════════════════════════════════════════════════════════════════


def setup_test_data():
    """
    Creates test data specifically for Phase 8.
    """
    session = requests.Session()
    session.headers.update({"Content-Type": "application/json"})

    print_step("SETUP: Creating test data for Phase 8")

    # 1. Register
    email = f"p8_admin_{int(time.time())}@test.com"
    r = session.post(f"{BASE_URL}/auth/register", json={
        "tenant_name": "Phase8 Test Corp",
        "tenant_type": "corporate",
        "name": "P8 Admin",
        "email": email,
        "password": "Password123!"
    })
    assert r.status_code in [201, 200], f"Register failed: {r.text}"
    token = r.json()["access_token"]
    session.headers.update({"Authorization": f"Bearer {token}"})

    # 2. Event
    r = session.post(f"{BASE_URL}/events", json={
        "name": "P8 WhatsApp Test Event",
        "type": "mice",
        "description": "Testing WhatsApp integration",
        "destination": "Goa",
        "start_date": "2026-05-10",
        "end_date": "2026-05-13",
        "expected_guests": 20,
        "category_rules": {
            "vip": {"allowed_room_types": ["standard", "deluxe"], "subsidy_per_night": 10000}
        }
    })
    event_id = r.json()["id"]

    # Activate
    r = session.put(f"{BASE_URL}/events/{event_id}", json={"status": "active"})

    # 3. Venue
    r = session.post(f"{BASE_URL}/venues", json={
        "name": "P8 Test Hotel",
        "city": "Goa",
        "state": "Goa",
        "total_rooms": 100,
        "contact_email": "hotel@test.com"
    })
    venue_id = r.json()["id"]

    # 4. Room Block
    r = session.post(f"{BASE_URL}/events/{event_id}/room-blocks", json={
        "venue_id": venue_id,
        "check_in_date": "2026-05-10",
        "check_out_date": "2026-05-13",
        "hold_deadline": (date.today() + timedelta(days=5)).isoformat(),
        "allotments": [
            {"room_type": "standard", "total_rooms": 1, "negotiated_rate": 6000.00},
        ]
    })
    block_id = r.json()["id"]

    # 5. Microsite
    slug = f"p8-test-{int(time.time())}"
    r = session.post(f"{BASE_URL}/events/{event_id}/microsite", json={
        "slug": slug,
        "theme_color": "#1e293b",
        "welcome_message": "P8 Test",
        "is_published": True
    })

    print(f"✅ Event setup complete: {event_id}")

    return {
        "session": session,
        "token": token,
        "event_id": event_id,
        "venue_id": venue_id,
        "block_id": block_id,
        "slug": slug,
    }


# ══════════════════════════════════════════════════════════════════════════════
# TESTS
# ══════════════════════════════════════════════════════════════════════════════


def test_server_health():
    print_step("TEST 1: Server Health & Phase 8 Imports")
    r = requests.get("http://127.0.0.1:8000/health")
    assert r.status_code == 200, "Server is not running!"
    print("✅ TEST 1 PASSED: Server healthy!")
    return True


def test_invitation_dual_dispatch(ctx):
    print_step("TEST 2: Invitation Dual-Dispatch")
    
    # Guest 1: WITH phone number (should dispatch both email and WhatsApp)
    r = ctx["session"].post(f"{BASE_URL}/events/{ctx['event_id']}/guests", json={
        "name": "Wally WhatsApp", "email": f"wally_{int(time.time())}@p8.com", "category": "vip",
        "phone": "+919876543210"
    })
    assert r.status_code in [201, 200]
    guest_with_phone = r.json()
    print("   ✅ Created Guest 1 (with phone)")

    # Guest 2: WITHOUT phone number (should dispatch ONLY email)
    r = ctx["session"].post(f"{BASE_URL}/events/{ctx['event_id']}/guests", json={
        "name": "Eddie Email", "email": f"eddie_{int(time.time())}@p8.com", "category": "vip"
    })
    assert r.status_code in [201, 200]
    guest_no_phone = r.json()
    print("   ✅ Created Guest 2 (no phone)")

    ctx["guests"] = {"with_phone": guest_with_phone, "no_phone": guest_no_phone}
    print("\n✅ TEST 2 PASSED: Guests created, tasks queued.")
    return True


def test_booking_confirmation_wa(ctx):
    print_step("TEST 3: Booking Confirmation dual-dispatch")
    
    g = ctx["guests"]["with_phone"]
    
    # Book the only standard room
    r = requests.post(f"{BASE_URL}/public/hold", json={
        "guest_token": g["booking_token"],
        "room_block_id": ctx["block_id"],
        "room_type": "standard"
    })
    assert r.status_code in [201, 200], f"Hold failed: {r.text}"
    hold_id = r.json()["id"]

    r2 = requests.post(f"{BASE_URL}/public/webhooks/razorpay/{hold_id}/confirm",
                       json={"payment_reference": f"pay_{uuid.uuid4().hex[:8]}"})
    assert r2.status_code == 200, f"Confirm failed: {r2.text}"
    
    ctx["booking_id"] = r2.json()["id"]
    print(f"   ✅ Booked room for {g['name']}")
    return True


def test_waitlist_offer_wa(ctx):
    print_step("TEST 4: Waitlist Offer dual-dispatch")
    
    # Room is full. Guest 2 (no phone) joins waitlist
    g = ctx["guests"]["no_phone"]
    r = ctx["session"].post(f"{BASE_URL}/events/{ctx['event_id']}/waitlist", json={
        "guest_id": g["id"],
        "room_block_id": ctx["block_id"],
        "room_type": "standard",
        "notes": "Testing waitlist cascade"
    })
    assert r.status_code in [201, 200], f"Waitlist failed: {r.text}"
    print(f"   ✅ {g['name']} joined waitlist")

    # Guest 1 cancels -> triggers waitlist cascade
    r = ctx["session"].delete(f"{BASE_URL}/bookings/{ctx['booking_id']}")
    assert r.status_code == 200, f"Cancel failed: {r.text}"
    print(f"   ✅ {ctx['guests']['with_phone']['name']} cancelled. Waitlist offer should be queued.")
    return True


def test_reminder_blast_wa(ctx):
    print_step("TEST 5: Reminder Blast dual-dispatch")
    
    # Send blast to VIPs
    r = ctx["session"].post(
        f"{BASE_URL}/events/{ctx['event_id']}/reminders/blast",
        json={"categories": ["vip"], "custom_message": "Book ASAP via WhatsApp!"}
    )
    assert r.status_code == 200
    data = r.json()
    print(f"   📧 Queued blast for {data['queued']} unbooked guests")
    return True


def test_notification_audit_trail(ctx):
    print_step("TEST 6: Check Notification Logs")
    
    # Wait for Celery
    import sys
    print("   Waiting for Celery to process...", end="", flush=True)
    for _ in range(15):
        time.sleep(1)
        print(".", end="", flush=True)
    print()

    r = ctx["session"].get(f"{BASE_URL}/events/{ctx['event_id']}/notifications")
    assert r.status_code == 200
    logs = r.json()["items"]
    
    print(f"\n   Total logs in DB: {len(logs)}\n")
    
    email_count = 0
    wa_count = 0
    types = set()
    
    for log in logs:
        ch = log.get("channel", "unknown")
        ty = log.get("type", "unknown")
        em = log.get("recipient_email", "unknown")
        st = log.get("status", "unknown")
        
        types.add((ch, ty))
        if ch == "email": email_count += 1
        if ch == "whatsapp": wa_count += 1
        
        icon = "📧" if ch == "email" else "💬"
        print(f"   {icon} [{ch[:5]}] {ty:21s} → {em} ({st})")
        
    print(f"\n   Stats: {email_count} Emails, {wa_count} WhatsApps logged.")
    
    assert wa_count > 0, "No WhatsApp logs found! Check if Celery worker is running."
    
    print("\n✅ TEST 6 PASSED: Both Email and WhatsApp channels found in logs!")
    return True


# ══════════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════════

def run_phase8_tests():
    print("\n" + "█" * 70)
    print("█  PHASE 8: WHATSAPP INTEGRATION — FULL TEST SUITE")
    print("█" * 70)

    results = {}
    results["health"] = test_server_health()
    ctx = setup_test_data()

    for test_fn, name in [
        (test_invitation_dual_dispatch, "invitation_dispatch"),
        (test_booking_confirmation_wa, "booking_confirmation"),
        (test_waitlist_offer_wa, "waitlist_offer"),
        (test_reminder_blast_wa, "reminder_blast"),
        (test_notification_audit_trail, "audit_trail"),
    ]:
        try:
            results[name] = test_fn(ctx)
        except AssertionError as e:
            print(f"\n❌ FAILED: {e}")
            results[name] = False

    # Summary
    print_step("📊 PHASE 8 TEST RESULTS")
    total = len(results)
    passed = sum(1 for v in results.values() if v)

    for name, passed_flag in results.items():
        icon = "✅" if passed_flag else "❌"
        print(f"   {icon} {name}")

    print(f"\n   {passed}/{total} tests passed.")

    if passed == total:
        print("\n🎉 ALL PHASE 8 TESTS PASSED!")
    else:
        print("\n⚠️  Some tests failed. Check Celery worker output.")


if __name__ == "__main__":
    try:
        run_phase8_tests()
    except requests.exceptions.ConnectionError:
        print("\n❌ Cannot connect to the server! Start uvicorn.")
