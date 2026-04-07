import requests
import uuid

BASE_URL = "http://localhost:8000/api/v1"

def create_demo_links():
    session = requests.Session()

    # 1. Login as planner
    print("Logging in as setup planner...")
    r = session.post(f"{BASE_URL}/auth/login", data={"username": "planner@e2e.com", "password": "password123"})
    if r.status_code != 200:
        print("Failed to login! Make sure you run `uv run python reset_db.py` and have the backend running.")
        return
    token = r.json()["access_token"]
    session.headers.update({"Authorization": f"Bearer {token}"})

    # ==========================================
    # EVENT 1: THE EXECUTIVE SANCTUARY (Gold)
    # ==========================================
    e1_payload = {
        "name": "TCS Annual Goa Retreat 2026",
        "destination": "THE ST. REGIS, GOA",
        "start_date": "2026-03-12",
        "end_date": "2026-03-15",
        "type": "wedding",
        "status": "draft",
        "category_rules": {
            "vip": {"allowed_room_types": ["standard", "deluxe", "suite"], "subsidy_per_night": 20000},
            "employee": {"allowed_room_types": ["standard", "deluxe"], "subsidy_per_night": 5000}
        }
    }
    r = session.post(f"{BASE_URL}/events", json=e1_payload)
    e1_id = r.json()["id"]

    session.post(f"{BASE_URL}/events/{e1_id}/blocks", json={"room_type": "standard", "total_rooms": 10, "negotiated_rate": 8000})
    session.post(f"{BASE_URL}/events/{e1_id}/blocks", json={"room_type": "deluxe", "total_rooms": 2, "negotiated_rate": 15000})
    session.post(f"{BASE_URL}/events/{e1_id}/blocks", json={"room_type": "suite", "total_rooms": 0, "negotiated_rate": 40000})

    slug1 = f"goa-retreat-{uuid.uuid4().hex[:4]}"
    session.post(f"{BASE_URL}/events/{e1_id}/microsite", json={
        "slug": slug1,
        "theme_color": "#c29b40", # The elegant Gold
        "welcome_message": "We have curated an exclusive selection of accommodation for your stay at the retreat. As a VIP attendee, your core experience is customized.",
        "is_published": True
    })

    g1_vip = session.post(f"{BASE_URL}/events/{e1_id}/guests", json={"name": "Raj Sharma (VIP)", "email": f"vip1_{uuid.uuid4().hex[:4]}@tcs.com", "category": "vip"}).json()
    g1_emp = session.post(f"{BASE_URL}/events/{e1_id}/guests", json={"name": "Arun Kumar (Employee)", "email": f"emp1_{uuid.uuid4().hex[:4]}@tcs.com", "category": "employee"}).json()

    # ==========================================
    # EVENT 2: THE MODERN STARTUP (Teal)
    # ==========================================
    e2_payload = {
        "name": "Eventflow Developer Summit 2026",
        "destination": "BANGALORE WEWORK",
        "start_date": "2026-06-01",
        "end_date": "2026-06-03",
        "type": "mice",
        "status": "draft",
        "category_rules": {
            "speaker": {"allowed_room_types": ["premium"], "subsidy_per_night": 10000},
            "attendee": {"allowed_room_types": ["hostel", "standard"], "subsidy_per_night": 0}
        }
    }
    r = session.post(f"{BASE_URL}/events", json=e2_payload)
    e2_id = r.json()["id"]

    session.post(f"{BASE_URL}/events/{e2_id}/blocks", json={"room_type": "premium", "total_rooms": 5, "negotiated_rate": 8000})
    session.post(f"{BASE_URL}/events/{e2_id}/blocks", json={"room_type": "hostel", "total_rooms": 50, "negotiated_rate": 1000})

    slug2 = f"dev-summit-{uuid.uuid4().hex[:4]}"
    session.post(f"{BASE_URL}/events/{e2_id}/microsite", json={
        "slug": slug2,
        "theme_color": "#0ea5e9", # Sky blue!
        "welcome_message": "Get ready for 48 hours of intense coding and building the future of group travel.",
        "is_published": True
    })

    g2_spk = session.post(f"{BASE_URL}/events/{e2_id}/guests", json={"name": "Alice Hacker", "email": f"speaker_{uuid.uuid4().hex[:4]}@dev.com", "category": "speaker"}).json()
    g2_att = session.post(f"{BASE_URL}/events/{e2_id}/guests", json={"name": "Bob Builder", "email": f"attendee_{uuid.uuid4().hex[:4]}@dev.com", "category": "attendee"}).json()

    # ==========================================
    # PRINT RESULTS
    # ==========================================
    print("\n" + "="*80)
    print("          TEST FRONTEND MICROSITE LINKS GENERATED SUCCESSFULLY")
    print("="*80 + "\n")
    
    print("EVENT 1: Goa Retreat (Executive Gold Theme)")
    print("-" * 50)
    print(f"1) As VIP:      http://localhost:3000/{slug1}?token={g1_vip['booking_token']}")
    print("   -> Expect zero balance for standard/deluxe, suite fully booked.")
    print(f"2) As Employee: http://localhost:3000/{slug1}?token={g1_emp['booking_token']}")
    print("   -> Expect standard/deluxe options, must pay remaining balance.\n")

    print("EVENT 2: Developer Summit (Tech Sky-Blue Theme)")
    print("-" * 50)
    print(f"3) As Speaker:  http://localhost:3000/{slug2}?token={g2_spk['booking_token']}")
    print("   -> Expect blue UI theme, subsidized premium block.")
    print(f"4) As Attendee: http://localhost:3000/{slug2}?token={g2_att['booking_token']}")
    print("   -> Expect blue UI theme, zero subsidy, must pay out of pocket.\n")

    print("\nMake sure your frontend is running via `npm run dev`!")

if __name__ == "__main__":
    create_demo_links()
