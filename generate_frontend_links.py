import asyncio
import uuid
from datetime import date, timedelta
from app.db.session import async_session
from app.models.tenant import Tenant
from app.models.user import User
from app.models.event import Event
from app.models.room_block import RoomBlock
from app.models.guest import Guest
from app.models.microsite import Microsite

async def generate_data():
    async with async_session() as db:
        # Create Dummy Tenant & User
        tenant_slug = f"test-corp-{uuid.uuid4().hex[:6]}"
        tenant = Tenant(name="Test Corp", slug=tenant_slug)
        db.add(tenant)
        await db.commit()
        await db.refresh(tenant)

        planner = User(tenant_id=tenant.id, name="Admin Planner", email="planner@test.com", password_hash="x", role="admin")
        db.add(planner)
        await db.commit()

        # -------------------------------------------------------------
        # EVENT 1: Executive Beach Retreat (Gold/Warm Theme)
        # -------------------------------------------------------------
        e1 = Event(
            tenant_id=tenant.id, created_by=planner.id,
            name="TCS Annual Goa Retreat", destination="THE ST. REGIS, GOA",
            type="wedding", status="active",
            start_date=date.today() + timedelta(days=30),
            end_date=date.today() + timedelta(days=35),
            category_rules={
                "vip": {"allowed_room_types": ["standard", "deluxe", "suite"], "subsidy_per_night": 20000},
                "employee": {"allowed_room_types": ["standard", "deluxe"], "subsidy_per_night": 5000}
            }
        )
        db.add(e1)
        await db.commit()
        await db.refresh(e1)

        tcs_slug = f"tcs-goa-{uuid.uuid4().hex[:6]}"
        m1 = Microsite(
            event_id=e1.id, tenant_id=tenant.id,
            slug=tcs_slug, theme_color="#c29b40",
            welcome_message="We have curated an exclusive selection of accommodation for your stay at the retreat. As a VIP attendee, your core experience is customized.",
            is_published=True
        )
        db.add(m1)

        rb1_std = RoomBlock(event_id=e1.id, room_type="standard", total_rooms=10, negotiated_rate=8000)
        rb1_dlx = RoomBlock(event_id=e1.id, room_type="deluxe", total_rooms=2, negotiated_rate=15000)
        rb1_ste = RoomBlock(event_id=e1.id, room_type="suite", total_rooms=0, negotiated_rate=40000)
        db.add_all([rb1_std, rb1_dlx, rb1_ste])

        g1_vip = Guest(event_id=e1.id, email="raj.vip@tcs.com", name="Raj Sharma", category="vip", status="none")
        g1_emp = Guest(event_id=e1.id, email="employee@tcs.com", name="Arun Kumar", category="employee", status="none")
        db.add_all([g1_vip, g1_emp])
        await db.commit()
        await db.refresh(g1_vip)
        await db.refresh(g1_emp)

        # -------------------------------------------------------------
        # EVENT 2: Tech Startup Hackathon (Teal/Modern Theme)
        # -------------------------------------------------------------
        e2 = Event(
            tenant_id=tenant.id, created_by=planner.id,
            name="Eventflow Developer Summit", destination="BANGALORE WEWORK",
            type="mice", status="active",
            start_date=date.today() + timedelta(days=60),
            end_date=date.today() + timedelta(days=62),
            category_rules={
                "speaker": {"allowed_room_types": ["premium"], "subsidy_per_night": 10000},
                "attendee": {"allowed_room_types": ["hostel", "standard"], "subsidy_per_night": 0}
            }
        )
        db.add(e2)
        await db.commit()
        await db.refresh(e2)

        summit_slug = f"eventflow-summit-{uuid.uuid4().hex[:6]}"
        m2 = Microsite(
            event_id=e2.id, tenant_id=tenant.id,
            slug=summit_slug, theme_color="#0ea5e9", # Tailwind sky-500
            welcome_message="Get ready for 48 hours of intense coding and building the future of group travel.",
            is_published=True
        )
        db.add(m2)

        rb2_hst = RoomBlock(event_id=e2.id, room_type="hostel", total_rooms=50, negotiated_rate=1000)
        rb2_prm = RoomBlock(event_id=e2.id, room_type="premium", total_rooms=5, negotiated_rate=8000)
        db.add_all([rb2_hst, rb2_prm])

        g2_spk = Guest(event_id=e2.id, email="speaker@eventflow.com", name="Alice Hacker", category="speaker", status="none")
        g2_att = Guest(event_id=e2.id, email="attendee@dev.com", name="Bob Builder", category="attendee", status="none")
        db.add_all([g2_spk, g2_att])
        await db.commit()
        await db.refresh(g2_spk)
        await db.refresh(g2_att)

        print("\\n" + "="*80)
        print("          TEST FRONTEND MICROSITE LINKS GENERATED SUCCESSFULLY")
        print("="*80 + "\\n")
        
        print("EVENT 1: Goa Retreat (Executive Gold Theme)")
        print("-" * 50)
        print(f"1) As VIP:      http://localhost:3000/{tcs_slug}?token={g1_vip.booking_token}")
        print("   -> Expect zero balance for standard/deluxe, suite fully booked.")
        print(f"2) As Employee: http://localhost:3000/{tcs_slug}?token={g1_emp.booking_token}")
        print("   -> Expect standard/deluxe options, must pay remaining balance.\\n")

        print("EVENT 2: Developer Summit (Tech Sky-Blue Theme)")
        print("-" * 50)
        print(f"3) As Speaker:  http://localhost:3000/{summit_slug}?token={g2_spk.booking_token}")
        print("   -> Expect blue UI theme, subsidized premium block.")
        print(f"4) As Attendee: http://localhost:3000/{summit_slug}?token={g2_att.booking_token}")
        print("   -> Expect blue UI theme, zero subsidy, must pay out of pocket.\\n")

if __name__ == "__main__":
    asyncio.run(generate_data())
