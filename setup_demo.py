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

    # 1. Register a new tenant & admin
    print_step("1. Registering Tenant & Admin")
    email = f"admin_{int(time.time())}@e2e.com"
    register_payload = {
        "tenant_name": "E2E Testing Corp",
        "tenant_type": "corporate",
        "name": "E2E Admin",
        "email": email,
        "password": "Password123!"
    }
    r = session.post(f"{BASE_URL}/auth/register", json=register_payload)
    print_response(r)
    assert r.status_code in [201, 200], "Failed to register"
    token = r.json().get("access_token")
    session.headers.update({"Authorization": f"Bearer {token}"})
    print(f"✅ Registered & Logged in as {email}")

    # 2. Create a Venue
    print_step("2. Creating Venue")
    venue_payload = {
        "name": "Grand E2E Palace",
        "city": "Goa",
        "state": "Goa",
        "total_rooms": 100,
        "contact_email": "hello@grandpalace.com"
    }
    r = session.post(f"{BASE_URL}/venues", json=venue_payload)
    print_response(r)
    assert r.status_code in [201, 200], "Failed to create venue"
    venue_id = r.json()["id"]
    print(f"✅ Created Venue: {venue_id}")

    # 3. Create an Event
    print_step("3. Creating Event")
    event_payload = {
        "name": "E2E Annual Offsite",
        "type": "mice",
        "description": "Integration testing event",
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
    }
    r = session.post(f"{BASE_URL}/events", json=event_payload)
    print_response(r)
    assert r.status_code in [201, 200], "Failed to create event"
    event_id = r.json()["id"]
    print(f"✅ Created Event: {event_id}")

    # 4. Create Room Block and Allotments
    print_step("4. Creating Room Block")
    block_payload = {
        "venue_id": venue_id,
        "check_in_date": "2026-03-15",
        "check_out_date": "2026-03-18",
        "hold_deadline": "2026-02-15",
        "notes": "Main block for employees",
        "allotments": [
            {
                "room_type": "standard",
                "total_rooms": 2,
                "negotiated_rate": 8000.00
            },
            {
                "room_type": "deluxe",
                "total_rooms": 5,
                "negotiated_rate": 12000.00
            },
            {
                "room_type": "suite",
                "total_rooms": 2,
                "negotiated_rate": 25000.00
            }
        ]
    }
    r = session.post(f"{BASE_URL}/events/{event_id}/room-blocks", json=block_payload)
    print_response(r)
    assert r.status_code in [201, 200], "Failed to create room block"
    print(f"✅ Created Room Block")

    # 5. Creating Event Microsite
    print_step("5. Creating Event Microsite")
    microsite_payload = {
        "slug": f"e2e-annual-offsite-{int(time.time() % 1000)}",
        "theme_color": "#c29b40", # Executive Gold
        "welcome_message": "Welcome to the Goa Offsite 2026!",
        "is_published": True
    }
    r = session.post(f"{BASE_URL}/events/{event_id}/microsite", json=microsite_payload)
    print_response(r)
    assert r.status_code in [201, 200], "Failed to create microsite"
    slug = microsite_payload["slug"]
    print(f"✅ Created Microsite with slug: {slug}")

    # 6. Creating Guests
    print_step("6. Creating Guests for Testing")
    guests = []
    guest_names = ["Alice (Employee)", "Bob (Employee)", "Charlie (Employee)", "Diana (VIP)"]
    categories = ["employee", "employee", "employee", "vip"]
    
    for idx, (name, cat) in enumerate(zip(guest_names, categories)):
        email_addr = f"guest{idx}_{int(time.time())}@e2e.com"
        g_payload = {
            "name": name,
            "email": email_addr,
            "category": cat
        }
        r = session.post(f"{BASE_URL}/events/{event_id}/guests", json=g_payload)
        assert r.status_code in [201, 200], f"Failed to create guest {name}"
        guests.append({
            "name": name,
            "category": cat,
            "token": r.json()['booking_token']
        })
        print(f"✅ Created Guest: {name} | Token: {r.json()['booking_token']}")

    # ============================================================
    # PRINT RESULTS
    # ==========================================
    print("\n" + "="*80)
    print("          TEST FRONTEND MICROSITE LINKS GENERATED SUCCESSFULLY")
    print("="*80 + "\n")
    
    print("Just Copy and Paste these links into your Browser to test the Frontend!")
    print(f"(Make sure Next.js is running at localhost:3000)\n")

    for g in guests:
        link = f"http://localhost:3000/{slug}?token={g['token']}"
        print(f"-> As {g['category'].upper()} | {g['name']}")
        print(f"   URL: {link}\n")

if __name__ == "__main__":
    run_setup()
