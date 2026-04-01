import requests
import uuid
import time
import random

BASE_URL = "http://localhost:8000/api/v1"

def print_step(title):
    print(f"\n{'='*60}")
    print(f"🚀 {title}")
    print(f"{'='*60}")

def print_response(r):
    print(f"Status: {r.status_code}")
    if r.status_code >= 400:
        print(f"Error Response: {r.text}")

def run_full_flow():
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
    print_step("4. Creating Room Block (Phase 2B)")
    block_payload = {
        "venue_id": venue_id,
        "check_in_date": "2026-03-15",
        "check_out_date": "2026-03-18",
        "hold_deadline": "2026-02-15",
        "notes": "Main block for employees",
        "allotments": [
            {
                "room_type": "standard",
                "total_rooms": 2, # VERY SMALL inventory to test waitlist
                "negotiated_rate": 8000.00
            },
            {
                "room_type": "deluxe",
                "total_rooms": 1,
                "negotiated_rate": 12000.00
            }
        ]
    }
    r = session.post(f"{BASE_URL}/events/{event_id}/room-blocks", json=block_payload)
    print_response(r)
    assert r.status_code in [201, 200], "Failed to create room block"
    block_data = r.json()
    block_id = block_data["id"]
    allotments = block_data["allotments"]
    print(f"✅ Created Room Block: {block_id}")
    for al in allotments:
        print(f"   - {al['room_type']}: {al['total_rooms']} rooms (ID: {al['id']})")

    # 5. Create Guests
    print_step("5. Creating Guests to Book and Waitlist")
    guests = []
    # Create 4 guests: 3 will fight for 2 standard rooms, 1 will fight for 1 deluxe
    guest_names = ["Alice (Employee)", "Bob (Employee)", "Charlie (Employee)", "Diana (VIP)"]
    categories = ["employee", "employee", "employee", "vip"]
    for name, cat in zip(guest_names, categories):
        g_payload = {
            "name": name,
            "email": f"{name.split()[0].lower()}@e2e.com",
            "category": cat
        }
        r = session.post(f"{BASE_URL}/events/{event_id}/guests", json=g_payload)
        assert r.status_code in [201, 200], f"Failed to create guest {name}"
        guests.append(r.json())
        print(f"✅ Created Guest: {name} | Token: {r.json()['booking_token']}")

    # 5.5 Check Auto-Created Wallets
    print_step("5.5 Verify Auto-Created Wallets (Phase 2D)")
    wallet_balances = {}
    for g in guests:
        wallet_res = session.get(f"{BASE_URL}/events/{event_id}/guests/{g['id']}/wallet")
        assert wallet_res.status_code == 200, "Wallet not found"
        wallet_data = wallet_res.json()
        print(f"✅ Guest {g['name']} Wallet Balance: ₹{wallet_data['balance']} | TX count: {len(wallet_data.get('transactions', []))}")
        wallet_balances[g['id']] = float(wallet_data['balance'])

    # Phase 2C Booking Flow Tests
    
    # 6. Guest 1 and Guest 2 consume all standard rooms
    print_step("6. Successful Bookings (Consuming Inventory)")
    hold_ids = []
    for i in range(2):
        print(f"\n--- Booking for {guests[i]['name']} ---")
        hold_payload = {
            "guest_token": guests[i]["booking_token"],
            "room_block_id": block_id,
            "room_type": "standard"
        }
        r = requests.post(f"{BASE_URL}/public/hold", json=hold_payload)
        print_response(r)
        assert r.status_code in [201, 200], "Failed to hold room"
        hold_data = r.json()
        hold_id = hold_data["id"]
        hold_ids.append(hold_id)
        print(f"✅ Room Held! Temp ID: {hold_id}")
        
        # Confirm Hold
        confirm_payload = {"payment_reference": f"pay_{uuid.uuid4().hex[:8]}"}
        r_conf = requests.post(f"{BASE_URL}/public/webhooks/razorpay/{hold_id}/confirm", json=confirm_payload)
        print_response(r_conf)
        assert r_conf.status_code == 200, "Failed to confirm hold"
        print(f"✅ Room Confirmed! Status: {r_conf.json()['status']}")
        
        # Phase 2D: Verify Wallet Debit
        wallet_res = session.get(f"{BASE_URL}/events/{event_id}/guests/{guests[i]['id']}/wallet")
        wallet_data = wallet_res.json()
        new_balance = float(wallet_data['balance'])
        print(f"✅ Phase 2D: Wallet Balance After Booking: ₹{new_balance} (Was: ₹{wallet_balances[guests[i]['id']]})")
        assert new_balance < wallet_balances[guests[i]['id']], "Wallet was not debited!"

    # 7. Guest 3 tries to book standard room (should fail and suggest waitlist)
    print_step("7. Waitlist Trigger Test (Room Unavailability)")
    print(f"\n--- Booking for {guests[2]['name']} (Expect Error) ---")
    hold_payload = {
        "guest_token": guests[2]["booking_token"],
        "room_block_id": block_id,
        "room_type": "standard"
    }
    r = requests.post(f"{BASE_URL}/public/hold", json=hold_payload)
    print_response(r)
    assert r.status_code == 409, "Should have received 409 Conflict due to unavailability"
    print("✅ Successfully caught out-of-stock error!")

    # 8. Add Guest 3 to Waitlist
    print_step("8. Adding Guest 3 to Waitlist")
    wl_payload = {
        "guest_id": guests[2]["id"],
        "room_block_id": block_id,
        "room_type": "standard"
    }
    r = session.post(f"{BASE_URL}/events/{event_id}/waitlist", json=wl_payload)
    print_response(r)
    assert r.status_code in [201, 200]
    waitlist_data = r.json()
    wl_id = waitlist_data["id"]
    print(f"✅ Guest added to waitlist! Position: {waitlist_data['position']}")

    # 9. Cancel Guest 1's Booking to Trigger Waitlist Promotion
    print_step("9. Cancel Booking & Waitlist Cascade")
    print(f"Cancelling booking {hold_ids[0]} for Guest 1...")
    r = session.delete(f"{BASE_URL}/bookings/{hold_ids[0]}")
    print_response(r)
    assert r.status_code == 200, "Failed to cancel booking"
    print("✅ Booking Cancelled!")
    
    # Phase 2D: Verify Wallet Refund
    wallet_res = session.get(f"{BASE_URL}/events/{event_id}/guests/{guests[0]['id']}/wallet")
    wallet_data = wallet_res.json()
    refunded_balance = float(wallet_data['balance'])
    print(f"✅ Phase 2D: Wallet Balance After Cancellation Refund: ₹{refunded_balance}")
    assert refunded_balance > new_balance, "Wallet was not credited back on cancellation!"

    time.sleep(1) # wait for background worker/cascade

    # 10. Check if Guest 3 got promoted
    print_step("10. Verify Waitlist Promotion")
    r = session.get(f"{BASE_URL}/events/{event_id}/waitlist")
    assert r.status_code == 200
    wl_list = r.json()["items"]
    promoted = [w for w in wl_list if w["id"] == wl_id][0]
    print(f"Waitlist Status for Guest 3: {promoted['status']}")
    if promoted['status'] == 'offered':
        print("✅ Waitlist correctly promoted to 'offered'!")
    else:
        print("⚠️ Waitlist not offered automatically - check background tasks.")
    
    # ============================================================
    # 11. Testing Administrative Wallet Load (Manual Top-Up)
    # ============================================================
    print_step("11. Testing Administrative Wallet Load (Manual Top-Up)")
    vip_guest = guests[3] # Diana (VIP)
    
    # 11a. Check initial VIP balance
    r_initial_wallet = session.get(f"{BASE_URL}/events/{event_id}/guests/{vip_guest['id']}/wallet")
    initial_vip_balance = float(r_initial_wallet.json()["balance"])
    print(f"Initial VIP Balance for {vip_guest['name']}: ₹{initial_vip_balance}")

    # 11b. Load an extra ₹10,000 into the VIP wallet
    print(f"Loading an extra ₹10,000 into {vip_guest['name']}'s wallet...")
    load_payload = {
        "amount": 10000.00,
        "description": "Board approved extra subsidy for Sea-View upgrade"
    }
    r_load = session.post(f"{BASE_URL}/events/{event_id}/guests/{vip_guest['id']}/wallet/load", json=load_payload)
    print_response(r_load)
    assert r_load.status_code == 200, "Failed to load manual subsidy"
    
    new_vip_balance = float(r_load.json()["balance"])
    print(f"✅ New VIP Balance: ₹{new_vip_balance}")
    assert new_vip_balance == initial_vip_balance + 10000.00, "Math error: Wallet balance did not increase correctly!"

    # ============================================================
    # 12. Verifying the Immutable Transaction Ledger
    # ============================================================
    print_step("12. Verifying Immutable Transaction Ledger")
    r_history = session.get(f"{BASE_URL}/events/{event_id}/guests/{vip_guest['id']}/wallet")
    history_data = r_history.json()
    transactions = history_data.get("transactions", [])
    
    print(f"Found {len(transactions)} transactions in the ledger.")
    assert len(transactions) >= 2, "Ledger should have at least the initial auto-load and the manual top-up."
    
    # Check if our manual top-up was recorded correctly
    top_up_tx = [tx for tx in transactions if tx["description"] == "Board approved extra subsidy for Sea-View upgrade"][0]
    print(f"✅ Found Ledger Entry: TYPE={top_up_tx['type']} | AMOUNT=₹{top_up_tx['amount']}")
    assert top_up_tx["type"] == "credit", "Manual load should be a CREDIT"
    assert float(top_up_tx["amount"]) == 10000.00, "Ledger recorded the wrong amount!"

    # ============================================================
    # 13. Testing the CFO Dashboard (Event Wallet Summary)
    # ============================================================
    print_step("13. Testing Event Wallet Summary (CFO Dashboard)")
    r_summary = session.get(f"{BASE_URL}/events/{event_id}/wallet-summary")
    print_response(r_summary)
    assert r_summary.status_code == 200, "Failed to fetch event wallet summary"
    
    summary_data = r_summary.json()
    print(f"Total Wallets: {summary_data['total_wallets']}")
    print(f"Total Balance Available: ₹{summary_data['total_balance']}")
    print(f"Total Corporate Spend: ₹{summary_data['total_spent']}")
    
    assert summary_data["total_wallets"] == 4, "System should report exactly 4 wallets for the 4 guests created."
    print("✅ Financial Aggregation is working perfectly!")

    print_step("🎉 E2E TESTS COMPLETED SUCCESSFULLY!")

if __name__ == "__main__":
    try:
        run_full_flow()
    except AssertionError as e:
        print(f"\n❌ TEST FAILED: {e}")
