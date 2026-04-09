import requests
import time

BASE_URL = "http://127.0.0.1:8000/api/v1"

def print_step(title):
    print(f"\n{'='*60}")
    print(f"🚀 {title}")
    print(f"{'='*60}")

def print_response(r):
    print(f"Status: {r.status_code}")
    if r.status_code >= 400:
        print(f"Error Response: {r.text}")

def run_setup():
    session = requests.Session()
    session.headers.update({"Content-Type": "application/json"})

    # 1. Register Tenant
    print_step("1. Registering Tenant & Admin")
    email = f"admin_{int(time.time())}@e2e.com"
    r = session.post(f"{BASE_URL}/auth/register", json={
        "tenant_name": "E2E Testing Corp",
        "tenant_type": "corporate",
        "name": "E2E Admin",
        "email": email,
        "password": "Password123!"
    })
    print_response(r)
    assert r.status_code in [201, 200]
    token = r.json().get("access_token")
    session.headers.update({"Authorization": f"Bearer {token}"})
    print(f"✅ Admin: {email}")

    # 2. Create Venue
    print_step("2. Creating Venue")
    r = session.post(f"{BASE_URL}/venues", json={
        "name": "Grand Goa Palace",
        "city": "Goa",
        "state": "Goa",
        "total_rooms": 100,
        "contact_email": "hello@grandgoa.com"
    })
    print_response(r)
    venue_id = r.json()["id"]
    print(f"✅ Venue: {venue_id}")

    # 3. Create Event
    # Category rules:
    #   employee → standard + deluxe allowed, ₹5000/night subsidy
    #   vip      → deluxe + suite allowed, ₹15000/night subsidy
    #
    # With 3 nights:
    #   employee subsidy total = ₹15,000
    #   vip subsidy total      = ₹45,000
    #
    # Standard  (₹8k/night × 3) = ₹24k → employee pays ₹9k
    # Deluxe    (₹12k/night × 3) = ₹36k → employee pays ₹21k | VIP pays ₹0 (FREE! ₹36k < ₹45k)
    # Suite     (₹25k/night × 3) = ₹75k → VIP pays ₹30k
    print_step("3. Creating Event")
    r = session.post(f"{BASE_URL}/events", json={
        "name": "Eventflow Annual Retreat",
        "type": "mice",
        "description": "Executive corporate retreat in Goa",
        "destination": "Goa",
        "start_date": "2026-03-15",
        "end_date": "2026-03-18",
        "expected_guests": 50,
        "category_rules": {
            "employee": {
                "allowed_room_types": ["standard", "deluxe"],
                "subsidy_per_night": 5000
            },
            "vip": {
                "allowed_room_types": ["deluxe", "suite"],
                "subsidy_per_night": 15000
            }
        }
    })
    print_response(r)
    event_id = r.json()["id"]
    print(f"✅ Event: {event_id}")

    # 4. Create Room Block
    # TIGHT inventory to force all lifecycle scenarios:
    #   Standard: 2 rooms  → Alice + Bob fill it → Charlie hits WAITLIST
    #   Deluxe:   3 rooms  → Dave + Eve + Frank fill it → Grace hits WAITLIST
    #   Suite:    1 room   → Diana (VIP) fills it → Bruce hits WAITLIST
    print_step("4. Creating Room Block (tight inventory)")
    r = session.post(f"{BASE_URL}/events/{event_id}/room-blocks", json={
        "venue_id": venue_id,
        "check_in_date": "2026-03-15",
        "check_out_date": "2026-03-18",
        "hold_deadline": "2026-02-15",
        "notes": "Main block — intentionally tight for lifecycle testing",
        "allotments": [
            {"room_type": "standard", "total_rooms": 2,  "negotiated_rate": 8000.00},
            {"room_type": "deluxe",   "total_rooms": 3,  "negotiated_rate": 12000.00},
            {"room_type": "suite",    "total_rooms": 1,  "negotiated_rate": 25000.00}
        ]
    })
    print_response(r)
    print(f"✅ Room Block created")

    # 5. Create Microsite
    print_step("5. Creating Event Microsite")
    slug = f"retreat-{int(time.time() % 10000)}"
    r = session.post(f"{BASE_URL}/events/{event_id}/microsite", json={
        "slug": slug,
        "theme_color": "#c29b40",
        "welcome_message": "Welcome to the Executive Retreat, Goa 2026!",
        "is_published": True
    })
    print_response(r)
    print(f"✅ Microsite slug: {slug}")

    # 6. Create Guests — designed to cover all 6 lifecycle scenarios
    print_step("6. Creating Guests (Scenario-Mapped)")

    # 10 employees + 4 VIPs
    # Each is labelled with the test scenario they're designed for
    guests_config = [
        # EMPLOYEES (standard + deluxe, sub = ₹15k/3nights)
        ("Alice",   "employee", "SCENARIO A1: Pays standard → CONFIRMED"),
        ("Bob",     "employee", "SCENARIO A2: Pays standard → CONFIRMED"),
        ("Charlie", "employee", "SCENARIO E:  Standard FULL → JOIN WAITLIST"),
        ("Dave",    "employee", "SCENARIO C:  Holds deluxe → CANCELS mid-hold"),
        ("Eve",     "employee", "SCENARIO D:  Pays deluxe → CANCELS confirmed (triggers Charlie waitlist cascade)"),
        ("Frank",   "employee", "SCENARIO A3: Pays deluxe → CONFIRMED"),
        ("Grace",   "employee", "SCENARIO A4: Pays deluxe → CONFIRMED"),
        ("Hank",    "employee", "SCENARIO E2: Deluxe FULL → JOIN WAITLIST"),
        ("Ivy",     "employee", "SCENARIO F:  Holds standard (if available) → let expire"),
        ("Jack",    "employee", "SCENARIO A5: Free observer / extra booking"),

        # VIPS (deluxe + suite, sub = ₹45k/3nights)
        ("Diana",   "vip", "SCENARIO B:  Books deluxe → FREE (₹36k < ₹45k subsidy) → CONFIRMED"),
        ("Bruce",   "vip", "SCENARIO A6: Books suite → ₹30k paid → CONFIRMED"),
        ("Clark",   "vip", "SCENARIO E3: Suite FULL → JOIN WAITLIST"),
        ("Tony",    "vip", "SCENARIO G:  Books deluxe (free) → CONFIRMED"),
    ]

    guests = []
    for idx, (name, cat, scenario) in enumerate(guests_config):
        email_addr = f"guest_{name.lower()}_{int(time.time())}@e2e.com"
        r = session.post(f"{BASE_URL}/events/{event_id}/guests", json={
            "name": name,
            "email": email_addr,
            "category": cat
        })
        assert r.status_code in [201, 200], f"Failed to create guest {name}: {r.text}"
        guests.append({
            "name": name,
            "category": cat,
            "scenario": scenario,
            "token": r.json()['booking_token']
        })
        print(f"  ✅ {name} ({cat})")

    # ─────────────────────────────────────────────────────────────────────────
    print("\n" + "="*80)
    print("   EVENTFLOW LIFECYCLE TEST — MICROSITE LINKS")
    print("="*80)
    print(f"\n   Event page: http://localhost:3000/{slug}?token=<TOKEN>")
    print(f"   Backend:    http://localhost:8000")
    print(f"   API Docs:   http://localhost:8000/docs\n")
    print("="*80)

    # Print subsidy cheat sheet
    print("\n💰 SUBSIDY CHEAT SHEET (3 nights)")
    print("-"*52)
    print(f"  EMPLOYEE subsidy: ₹5,000 × 3 = ₹15,000")
    print(f"  Standard  ₹8k×3 = ₹24k   → pays ₹9,000    [2 rooms]")
    print(f"  Deluxe    ₹12k×3= ₹36k   → pays ₹21,000   [3 rooms]")
    print(f"  VIP subsidy:     ₹15,000 × 3 = ₹45,000")
    print(f"  Deluxe    ₹12k×3= ₹36k   → pays ₹0 FREE   ← VIP fully covered!")
    print(f"  Suite     ₹25k×3= ₹75k   → pays ₹30,000   [1 room]")

    # Print links grouped by category
    print("\n" + "─"*80)
    print("🧪 EMPLOYEE LINKS (Scenarios A, C, D, E, F)")
    print("─"*80)
    for g in guests:
        if g["category"] == "employee":
            link = f"http://localhost:3000/{slug}?token={g['token']}"
            print(f"\n  [{g['name']}] — {g['scenario']}")
            print(f"  URL: {link}")

    print("\n" + "─"*80)
    print("👑 VIP LINKS (Scenarios B, A6, E3, G)")
    print("─"*80)
    for g in guests:
        if g["category"] == "vip":
            link = f"http://localhost:3000/{slug}?token={g['token']}"
            print(f"\n  [{g['name']}] — {g['scenario']}")
            print(f"  URL: {link}")

    print("\n" + "="*80)
    print("📋 WALKTHROUGH ORDER")
    print("="*80)
    print("""
STEP 1  → Alice:   Books standard, pays → CONFIRMED (green banner on refresh)
STEP 2  → Bob:     Books standard, pays → CONFIRMED
STEP 3  → Charlie: Visits → Standard FULLY BOOKED → JOIN WAITLIST (see position #1)
STEP 4  → Dave:    Claims deluxe, CANCELS during checkout → hold released
STEP 5  → Eve:     Pays deluxe → CONFIRMED → then CANCELS from confirmation page
          (Charlie auto-promoted → check Charlie's link for "ROOM OFFERED!" banner)
STEP 6  → Frank:   Books deluxe, pays → CONFIRMED
STEP 7  → Grace:   Books deluxe, pays → CONFIRMED  
STEP 8  → Hank:    Visits → Deluxe FULLY BOOKED → JOIN WAITLIST (see position #1)
STEP 9  → Diana:   Books deluxe as VIP → FREE (auto-confirm) → CONFIRMED
STEP 10 → Bruce:   Books suite, pays ₹30k → CONFIRMED
STEP 11 → Clark:   Visits → Suite FULLY BOOKED → JOIN WAITLIST
STEP 12 → Alice:   Revisit link → Green CONFIRMED banner (no double booking possible)
""")

if __name__ == "__main__":
    run_setup()