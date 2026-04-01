
# Eventflow Backend — Deep Dive Explained

Everything about the backend: what it is, why we need it, who it serves, what problems it solves, and what system design concepts power it.

---

## Table of Contents

1. [The Backend at a Glance](#1-the-backend-at-a-glance)
2. [Who We're Building For — User-by-User Breakdown](#2-who-were-building-for)
3. [The Backend Modules — Layer by Layer](#3-the-backend-modules)
4. [System Design Concepts — Why We Need Them](#4-system-design-concepts)
5. [Innovations — What Makes This Special](#5-innovations)
6. [How It All Connects — End-to-End Flows](#6-end-to-end-flows)

---

## 1. The Backend at a Glance

Our backend is a **FastAPI (Python)** application structured as a **modular monolith**. That means it looks like microservices on the inside (clean module boundaries, separate concerns) but runs as a single deployable unit. This is the industry standard for startups and resume projects — even Shopify ran as a monolith for years.

```
eventflow-backend/
│
├── app/
│   ├── main.py                  # FastAPI app entry point
│   ├── config.py                # Environment variables, settings
│   │
│   ├── api/                     # HTTP layer — routes only, no logic here
│   │   ├── v1/
│   │   │   ├── auth.py          # Login, register, token refresh
│   │   │   ├── events.py        # Event CRUD
│   │   │   ├── venues.py        # Venue search & discovery
│   │   │   ├── inventory.py     # Room blocks
│   │   │   ├── guests.py        # Guest list management
│   │   │   ├── bookings.py      # Booking creation, cancellation
│   │   │   ├── payments.py      # Split payments, ledger
│   │   │   ├── microsites.py    # Microsite config
│   │   │   ├── analytics.py     # Dashboard data
│   │   │   └── import_export.py # ETL upload, rooming list export
│   │   └── websocket.py         # WebSocket endpoints
│   │
│   ├── core/                    # Business logic — the brain
│   │   ├── auth/
│   │   │   ├── service.py       # Auth logic (hash, verify, JWT)
│   │   │   ├── rbac.py          # Role-based access control
│   │   │   └── tenant.py        # Tenant resolution & isolation
│   │   ├── events/
│   │   │   └── service.py       # Event creation, status management
│   │   ├── venues/
│   │   │   ├── search.py        # NLP search engine
│   │   │   ├── ranking.py       # Multi-criteria ranking algorithm
│   │   │   └── embeddings.py    # Vector embedding generation
│   │   ├── inventory/
│   │   │   ├── service.py       # Room block management
│   │   │   └── concurrency.py   # Locking, race condition handling
│   │   ├── booking/
│   │   │   ├── service.py       # Booking creation, cancellation
│   │   │   └── waitlist.py      # Waitlist logic
│   │   ├── payments/
│   │   │   ├── split_ledger.py  # Split payment calculation
│   │   │   ├── wallet.py        # Corporate wallet management
│   │   │   └── razorpay.py      # Payment gateway integration
│   │   ├── notifications/
│   │   │   ├── email.py         # Email templates & sending
│   │   │   └── reminders.py     # Scheduled reminder logic
│   │   ├── ingestion/
│   │   │   ├── parser.py        # Excel/PDF file parsing
│   │   │   ├── extractor.py     # Gemini-powered data extraction
│   │   │   └── validator.py     # Data validation & cleaning
│   │   └── analytics/
│   │       ├── dashboard.py     # Real-time metrics
│   │       └── forecasting.py   # Demand prediction
│   │
│   ├── models/                  # SQLAlchemy ORM models (database tables)
│   │   ├── tenant.py
│   │   ├── user.py
│   │   ├── event.py
│   │   ├── venue.py
│   │   ├── room_block.py
│   │   ├── guest.py
│   │   ├── booking.py
│   │   ├── payment.py
│   │   └── microsite.py
│   │
│   ├── schemas/                 # Pydantic models (request/response validation)
│   │   ├── auth.py
│   │   ├── event.py
│   │   ├── venue.py
│   │   ├── booking.py
│   │   └── payment.py
│   │
│   ├── middleware/              # Request processing pipeline
│   │   ├── auth.py              # JWT verification
│   │   ├── tenant.py            # Tenant context injection
│   │   ├── rate_limit.py        # API rate limiting
│   │   └── logging.py           # Request/response logging
│   │
│   ├── db/                      # Database layer
│   │   ├── session.py           # Connection pool, async sessions
│   │   ├── migrations/          # Alembic migrations
│   │   └── seed.py              # Seed data for demo
│   │
│   └── tasks/                   # Background jobs (Celery)
│       ├── email_tasks.py       # Async email sending
│       ├── reminder_tasks.py    # Scheduled reminders
│       └── release_tasks.py     # Auto-release expired room blocks
│
├── tests/
│   ├── test_concurrency.py      # Race condition tests
│   ├── test_payments.py         # Split payment edge cases
│   └── test_search.py           # NLP search tests
│
├── alembic.ini                  # Database migration config
├── requirements.txt
├── Dockerfile
└── docker-compose.yml
```

### Why This Structure Matters

Every file has ONE job. The `api/` layer only handles HTTP. The `core/` layer only handles business logic. The `models/` layer only defines database tables. This is called **Separation of Concerns** — and interviewers will specifically ask about it.

---

## 2. Who We're Building For

Let's break down exactly who uses what, what problem we solve for them, and which backend module handles it.

---

### 👔 User 1: The Planner (Corporate Travel Manager / Wedding Planner)

This is the **primary user**. They pay for the platform. Everything revolves around making their life easier.

#### What they do today (the pain):
| Step | Current Process | Time Wasted |
|------|----------------|-------------|
| 1. Find venues | Google hotels, call 8 sales managers | 3-4 days |
| 2. Get rate quotes | Wait for email replies | 2-5 days |
| 3. Negotiate rates | Back-and-forth email chains | 2-3 days |
| 4. Share info with guests | Send PDF attachment via email | Ongoing confusion |
| 5. Track RSVPs | Shared Google Sheet | Constant manual updates |
| 6. Chase non-bookers | WhatsApp messages one by one | 1-2 hours daily |
| 7. Create rooming list | Manually compile from sheet | Half day, error-prone |
| **Total** | | **2-3 weeks + ongoing stress** |

#### What Eventflow gives them:

| Feature | Backend Module | Problem Solved |
|---------|---------------|----------------|
| **NLP Venue Search** | `core/venues/search.py` | "Find me 5-star hotels in Goa with 200 rooms and conference hall" → instant ranked results instead of 8 phone calls |
| **Event Creation** | `core/events/service.py` | One place to define event dates, guest categories, pricing rules, deadlines |
| **Room Block Management** | `core/inventory/service.py` | Lock X rooms at negotiated rate, see consumption in real-time, no spreadsheet |
| **Guest Import (ETL)** | `core/ingestion/parser.py` | Upload Excel of 500 employees → auto-parsed into guest list. No manual typing |
| **Auto-Generated Microsite** | `core/events/service.py` + `models/microsite.py` | Branded booking page auto-created. Share one link, not a PDF |
| **Live Dashboard** | `core/analytics/dashboard.py` + WebSocket | See bookings happening in real-time. No more counting spreadsheet rows |
| **Automated Reminders** | `tasks/reminder_tasks.py` | System chases non-bookers, not you |
| **Rooming List Export** | `api/v1/import_export.py` | One-click export. No manual compilation |
| **Demand Forecasting** | `core/analytics/forecasting.py` | "At current pace, you'll be 80% full by Feb 28" — data-driven decisions |
| **Corporate Wallet** | `core/payments/wallet.py` | Set per-person subsidy. System handles the math |

**API endpoints the planner uses:**
```
POST   /api/v1/venues/search           → Find venues via NLP
POST   /api/v1/events                  → Create event
POST   /api/v1/events/{id}/blocks      → Create room block
POST   /api/v1/events/{id}/guests/import → Upload guest Excel
GET    /api/v1/events/{id}/dashboard   → Analytics
GET    /api/v1/events/{id}/rooming-list → Export
WS     /ws/event/{id}/dashboard        → Live updates
```

---

### 🧳 User 2: The Guest (Employee / Wedding Guest)

The person who actually books a room. They're **not tech-savvy**, booking on mobile, and confused by options. Our job is to make this **impossible to get wrong**.

#### What they face today (the pain):
- Receive a long email with a PDF explaining how to book
- Call the coordinator asking "which room type should I pick?"
- Book wrong dates because the email was unclear
- No idea if their booking went through until someone confirms manually

#### What Eventflow gives them:

| Feature | Backend Module | Problem Solved |
|---------|---------------|----------------|
| **Unique Booking Link** | `models/guest.py` → `unique_token` | No login. Click link → you're identified. Zero friction |
| **Constrained Booking Flow** | `core/booking/service.py` | Guest can ONLY see options valid for their category. Can't pick wrong room type or wrong dates |
| **Instant Confirmation** | `core/booking/service.py` → `tasks/email_tasks.py` | Book → instant email confirmation with itinerary. No waiting for manual approval |
| **Waitlist Auto-Notify** | `core/booking/waitlist.py` | Room full? Auto-added to waitlist. If someone cancels, you're next — notified immediately |
| **Event-Branded Experience** | `models/microsite.py` | See event name, dates, itinerary, venue map — not a generic hotel booking page |

**API endpoints the guest uses:**
```
GET    /api/v1/microsite/{slug}        → Load event page (no auth)
GET    /api/v1/microsite/{slug}/rooms  → Available room options (filtered by category)
POST   /api/v1/bookings               → Book a room
GET    /api/v1/bookings/{token}        → View my booking status
DELETE /api/v1/bookings/{id}           → Cancel booking
```

> [!IMPORTANT]
> **Notice:** The guest never logs in. Their `unique_token` in the URL is their identity. This is a deliberate architectural decision — it reduces friction to near zero for non-technical users (wedding guests, older family members, etc.).

---

### 🏨 User 3: The Hotel / Venue

The supply side. Hotels currently have no real-time visibility into how group blocks are being consumed. They allocate rooms blindly and risk either double-booking or leaving rooms empty.

#### What they face today:
- Group blocks allocated offline via email
- No system tracks consumption until the planner sends a rooming list (often late)
- Risk of double-booking the same room to a group AND a walk-in guest
- Manually releasing unclaimed rooms back to public inventory — often too late, losing revenue

#### What Eventflow gives them:

| Feature | Backend Module | Problem Solved |
|---------|---------------|----------------|
| **Digital Allotment Dashboard** | `core/inventory/service.py` | See in real-time: 45/100 rooms booked for Event X |
| **Auto-Release at Deadline** | `tasks/release_tasks.py` | Unclaimed rooms automatically released back to public inventory at a configured deadline. No manual work, no missed revenue |
| **Zero Double-Booking** | `core/inventory/concurrency.py` | Database-level `SELECT FOR UPDATE` lock prevents any possibility of selling the same room twice |
| **Consumption Analytics** | `core/analytics/dashboard.py` | "Corporate events fill 90% of blocks. Weddings fill 70%. Adjust pricing accordingly" |

**API endpoints the hotel uses:**
```
GET    /api/v1/hotel/allotments        → View all active room blocks
GET    /api/v1/hotel/allotments/{id}   → Block consumption details
PUT    /api/v1/hotel/allotments/{id}   → Update rates, extend deadline
GET    /api/v1/hotel/analytics         → Booking pattern analytics
```

---

## 3. The Backend Modules — Layer by Layer

Let's go through each module, what it does, why it exists, and what system design concept it uses.

---

### Module 1: Authentication & Multi-Tenancy (`core/auth/`)

#### What it does:
Handles who you are (authentication) and what you're allowed to do (authorization), AND ensures one tenant's data is completely invisible to another tenant.

#### The three layers:

```
┌──────────────────────────────────────────────┐
│  Layer 1: AUTHENTICATION                      │
│  "Who are you?"                               │
│  JWT tokens, password hashing, token refresh  │
├──────────────────────────────────────────────┤
│  Layer 2: AUTHORIZATION (RBAC)                │
│  "What can you do?"                           │
│  Roles: admin, planner, viewer, hotel_admin   │
│  Permissions: create_event, manage_blocks...  │
├──────────────────────────────────────────────┤
│  Layer 3: TENANT ISOLATION                    │
│  "What data can you see?"                     │
│  PostgreSQL Row-Level Security                │
│  Every query auto-filtered by tenant_id       │
└──────────────────────────────────────────────┘
```

#### Problem from the problem statement it solves:
> *"Creating dedicated inventory per group, with negotiated rates, protected allotments, inclusions, and validity mapped to a specific event"*

Tenant isolation ensures that Company A's events, guests, and bookings are completely invisible to Company B. This is not optional — it's the foundation of trust in a B2B platform.

#### How the request lifecycle works:

```
1. Planner sends request with JWT token in header
2. Auth middleware extracts JWT → gets user_id, tenant_id, role
3. Tenant middleware runs: SET app.tenant_id = '{tenant_id}'
4. PostgreSQL RLS policy auto-filters ALL queries
5. Even if code forgets WHERE tenant_id = ?, the database blocks it
6. RBAC middleware checks: does this role have permission for this action?
7. Request reaches the route handler — safe, isolated, authorized
```

---

### Module 2: Event Management (`core/events/`)

#### What it does:
CRUD for events + the complex configuration that makes each event unique (category rules, pricing tiers, booking deadlines, microsite settings).

#### The data it manages:

```
Event
├── Basic info: name, type (mice/wedding), dates, destination
├── Category Rules (JSONB):
│   ├── "employee": { room_types: ["standard", "deluxe"], subsidy: 8000 }
│   ├── "vip": { room_types: ["suite"], subsidy: 15000 }
│   └── "family": { room_types: ["deluxe", "suite"], subsidy: 0 }
├── Booking Deadlines:
│   ├── early_bird_deadline: "2026-02-15"
│   └── final_deadline: "2026-03-01"
├── Status lifecycle: draft → active → completed → cancelled
└── Microsite: theme, content, URL slug
```

#### Problem it solves:
> *"Different room rates for different guest categories (close family, friends, international guests)"*
> *"Guests booking wrong room types or wrong dates because instructions were in a PDF attachment nobody read"*

The `category_rules` JSONB field is the key. When a guest opens the booking page, the system checks their category and ONLY shows them allowed room types at the correct price. It's impossible to book the wrong thing because wrong options literally don't appear.

---

### Module 3: Venue Discovery (`core/venues/`)

#### What it does:
The PS1 integration — the entry point to the entire platform. A planner searches in natural language, and we return ranked venue results.

#### The pipeline:

```
"200-person offsite in Goa, March, needs conference hall, budget ₹12K"
                            │
                            ▼
         ┌─────────────────────────────────┐
         │   Step 1: NLP EXTRACTION         │
         │   Gemini API parses natural      │
         │   language → structured JSON      │
         │   {city: "Goa", capacity: 200,   │
         │    amenities: ["conference_hall"],│
         │    budget: 12000, month: "March"} │
         └──────────────┬──────────────────┘
                        ▼
         ┌─────────────────────────────────┐
         │   Step 2: HARD FILTER (SQL)      │
         │   WHERE city = 'Goa'             │
         │   AND total_rooms >= 200         │
         │   AND pricing <= 12000           │
         └──────────────┬──────────────────┘
                        ▼
         ┌─────────────────────────────────┐
         │   Step 3: SEMANTIC MATCH         │
         │   pgvector cosine similarity     │
         │   "conference hall" matches       │
         │   venues with "meeting rooms",   │
         │   "business center", etc.         │
         └──────────────┬──────────────────┘
                        ▼
         ┌─────────────────────────────────┐
         │   Step 4: COMPOSITE RANKING      │
         │   Score = 0.3×price_fit          │
         │        + 0.3×availability        │
         │        + 0.2×amenity_match       │
         │        + 0.1×rating              │
         │        + 0.1×distance_to_airport │
         └──────────────┬──────────────────┘
                        ▼
         Ranked list of venues with scores
```

#### Problem it solves:
> *"Sends RFQs to 10 hotels via email, waits days for responses"*
> *"Natural language venue search with group-rate availability surfaced instantly"*

Without this, a planner still has to Google hotels manually before even using our platform. This makes Eventflow the **starting point** of the entire workflow, not just a booking tool.

---

### Module 4: Inventory Management (`core/inventory/`)

#### What it does:
Manages room blocks — the core unit of group travel. A room block is X rooms held at a negotiated rate for a specific event, with a deadline for consumption.

#### The lifecycle of a room block:

```
CREATED                 ACTIVE                  DEADLINE
   │                      │                       │
   │  Planner creates     │  Guests book rooms    │  Auto-release
   │  block: 50 rooms     │  from this block      │  unclaimed rooms
   │  at ₹10K/night       │  (concurrency-safe)   │  back to hotel
   │  deadline: March 1   │                       │
   ▼                      ▼                       ▼
┌──────────┐      ┌──────────────┐      ┌──────────────┐
│ total: 50│      │ total: 50    │      │ total: 50    │
│ booked: 0│      │ booked: 35   │      │ booked: 35   │
│ held: 50 │      │ held: 15     │      │ held: 0      │
│          │      │              │      │ RELEASED: 15 │
└──────────┘      └──────────────┘      └──────────────┘
```

#### Problem it solves:
> *"Digitally locking inventory to a single group, ensuring controlled consumption and eliminating manual tracking"*
> *"Group blocks allocated offline, no system to track consumption digitally"*
> *"Risk of selling same room to both a group and a retail guest (double booking)"*

This is the **technical heart** of the project. The concurrency control here is what separates "student project" from "production-grade system."

---

### Module 5: Booking Engine (`core/booking/`)

#### What it does:
Creates bookings (the transaction where a guest claims a room from a block) and manages cancellations with automatic waitlist promotion.

#### The booking transaction — step by step:

```
Guest clicks "Book Now"
        │
        ▼
┌───────────────────────────────────┐
│  1. Validate guest's token         │  → Is this a real guest for this event?
│  2. Check category permissions     │  → Can this guest's category book this room type?
│  3. ACQUIRE ROW LOCK on block      │  → SELECT ... FOR UPDATE (blocks other transactions)
│  4. Check availability             │  → booked_rooms < total_rooms?
│  5. If full → add to waitlist      │  → Return "waitlisted" status
│  6. If available → increment count │  → booked_rooms += 1
│  7. Create booking record          │  → With check-in, check-out, price
│  8. Calculate split payment        │  → Corporate subsidy vs guest payment
│  9. COMMIT transaction             │  → Lock released, booking persisted
│  10. Publish event to Redis        │  → Dashboard updates in real-time
│  11. Send confirmation email       │  → Async via Celery task
└───────────────────────────────────┘
```

#### The cancellation + waitlist flow:

```
Guest cancels booking
        │
        ▼
┌───────────────────────────────────┐
│  1. Mark booking as "cancelled"    │
│  2. Decrement block.booked_rooms   │
│  3. Refund payment (if applicable) │
│  4. Check waitlist for this block  │
│  5. If someone waiting:            │
│     → Auto-offer room to #1        │
│     → Send notification email      │
│     → They have 24 hours to accept │
│  6. If nobody waiting:             │
│     → Room returns to available    │
│  7. Publish update to Redis        │
└───────────────────────────────────┘
```

#### Problem it solves:
> *"Manual release of unclaimed rooms back to public inventory often happens too late"*
> *"No way to see who else from their group has arrived or what the itinerary is"*
> *"Centralizing guest bookings and confirmations, replacing email-based coordination"*

---

### Module 6: Payment Engine (`core/payments/`)

#### What it does:
Handles the split-ledger logic where a corporate sponsor pays part of each booking and the guest pays the rest. Maintains an append-only audit trail.

#### The split calculation:

```
┌─────────────────────────────────────────────────────────┐
│                   PAYMENT CALCULATION                    │
│                                                         │
│  Room price:           ₹12,000/night                    │
│  Nights:               3                                │
│  Total:                ₹36,000                          │
│                                                         │
│  Guest category:       "employee"                       │
│  Subsidy rule:         ₹8,000/night max                 │
│  Corporate pays:       ₹8,000 × 3 = ₹24,000            │
│  Guest pays:           ₹12,000 - ₹8,000 = ₹4,000 × 3   │
│                      = ₹12,000                          │
│                                                         │
│  ┌──────────────────────────────────────────────────┐   │
│  │  PAYMENT_LEDGER entries (append-only):            │   │
│  │                                                    │   │
│  │  Row 1: corporate_subsidy  ₹24,000  ✅ completed   │   │
│  │  Row 2: guest_payment      ₹12,000  ⏳ pending     │   │
│  │  Row 3: guest_payment      ₹12,000  ✅ completed   │   │
│  └──────────────────────────────────────────────────┘   │
│                                                         │
│  Note: Row 2 → Row 3 happens when Razorpay confirms    │
│  We NEVER update rows. We append. This is EVENT SOURCING│
└─────────────────────────────────────────────────────────┘
```

#### Problem it solves:
> *"In corporate travel, the company often subsidizes the trip. Managing this math manually across 500 employees is an accounting nightmare."*

---

### Module 7: Smart Ingestion ETL (`core/ingestion/`)

#### What it does:
Takes messy real-world data (an Excel file with 500 guest names, a PDF hotel contract) and converts it into clean, structured database entries.

#### The pipeline:

```
Planner uploads "guest_list.xlsx"
        │
        ▼
┌───────────────────────────────────────┐
│  STEP 1: FILE PARSING                 │
│  pandas reads Excel → raw DataFrame   │
│  Handles: .xlsx, .csv, .pdf           │
│  (PDF uses pdfplumber for extraction)  │
└──────────────┬────────────────────────┘
               ▼
┌───────────────────────────────────────┐
│  STEP 2: LLM EXTRACTION               │
│  Send raw data to Gemini with prompt:  │
│  "Extract: name, email, phone,         │
│   department, role, room preference.   │
│   Handle messy formatting."            │
│                                        │
│  Input:  "Rahul S, Eng dept, wants     │
│           sea-facing room"             │
│  Output: {name: "Rahul S",            │
│           department: "Engineering",    │
│           room_pref: "sea_view"}       │
└──────────────┬────────────────────────┘
               ▼
┌───────────────────────────────────────┐
│  STEP 3: VALIDATION                    │
│  - Email format check (regex)          │
│  - Duplicate detection (fuzzy match)   │
│  - Missing required field flagging     │
│  - Category auto-assignment            │
│                                        │
│  Result: 480 clean / 20 need review    │
└──────────────┬────────────────────────┘
               ▼
┌───────────────────────────────────────┐
│  STEP 4: HUMAN REVIEW                  │
│  Planner sees a review UI:             │
│  - 480 green rows (auto-approved)      │
│  - 20 yellow rows (needs attention)    │
│  - Planner fixes/approves              │
└──────────────┬────────────────────────┘
               ▼
┌───────────────────────────────────────┐
│  STEP 5: BULK INSERT                   │
│  500 guest records → guest_list table  │
│  Each gets a unique_token for booking  │
│  Celery sends invitation emails        │
└───────────────────────────────────────┘
```

#### Problem it solves:
> *"Planners refuse to manually type 500 guest names into a new software platform. If onboarding is hard, they won't use the product."*

---

### Module 8: Notifications (`core/notifications/` + `tasks/`)

#### What it does:
Sends emails, triggers reminders, handles all communication. Runs ASYNCHRONOUSLY via Celery so the main API stays fast.

#### The notification types:

| Trigger | Recipient | What Gets Sent |
|---------|-----------|----------------|
| Guest added to event | Guest | Invitation email with booking link |
| Booking confirmed | Guest | Confirmation with itinerary, venue map |
| 7 days before deadline | Non-booked guests | "You haven't booked yet!" reminder |
| 3 days before deadline | Non-booked guests | "Final reminder — book now" |
| Cancellation by guest | Next on waitlist | "A room is available — book within 24h" |
| Block 80% consumed | Planner | "Your event is nearly full" |
| Block deadline reached | Planner + Hotel | "Unclaimed rooms released" |

#### Why async (Celery)?
Sending an email takes 1-2 seconds. If we did this during the booking API call, the user would wait 1-2 seconds for their booking confirmation page to load. Instead, we queue the email in Redis, return the booking response instantly, and a Celery worker picks up the email task in the background.

---

### Module 9: Analytics & Forecasting (`core/analytics/`)

#### What it does:
Provides real-time dashboards and predictive analytics for planners and hotels.

#### The dashboard metrics:

```
┌─────────────────────────────────────────────────────┐
│                 EVENT DASHBOARD                      │
│                                                      │
│  ┌─────────┐  ┌─────────┐  ┌─────────┐  ┌────────┐ │
│  │ 245/300 │  │  82%    │  │ 12 days │  │ 23     │ │
│  │ booked  │  │ filled  │  │ left    │  │ waitlst│ │
│  └─────────┘  └─────────┘  └─────────┘  └────────┘ │
│                                                      │
│  ┌──────────────────────────────────────────────┐   │
│  │  BOOKING PACE (line chart)                    │   │
│  │  ████████████████████░░░░░░░                  │   │
│  │  (25 bookings/day → projected full by Mar 5)  │   │
│  └──────────────────────────────────────────────┘   │
│                                                      │
│  ┌──────────────────────────────────────────────┐   │
│  │  BY CATEGORY                                  │   │
│  │  Employees:  180/200  ██████████████████░░ 90%│   │
│  │  VIPs:       40/50    ████████████████░░░░ 80%│   │
│  │  Family:     25/50    ██████████░░░░░░░░░ 50%│   │
│  └──────────────────────────────────────────────┘   │
│                                                      │
│  Forecast: "At current pace, full by March 5.       │
│  Consider releasing 10 held rooms now."              │
└─────────────────────────────────────────────────────┘
```

#### Demand forecasting (the math):
```python
def forecast_fill_date(event_id):
    """
    Simple linear regression on booking pace.
    Calculates when the event will be fully booked
    based on the current daily booking rate.
    """
    # Get bookings per day for last 14 days
    daily_bookings = get_daily_booking_counts(event_id, days=14)
    avg_rate = sum(daily_bookings) / len(daily_bookings)  # e.g., 25/day

    remaining = total_rooms - booked_rooms  # e.g., 55 remaining
    days_to_full = remaining / avg_rate     # 55/25 = 2.2 days

    projected_full_date = today + timedelta(days=days_to_full)
    return projected_full_date  # March 5
```

---

## 4. System Design Concepts — Why We Need Each One

This section is your **interview cheat sheet**. Each concept maps directly to a feature.

---

### Concept 1: Multi-Tenancy with Row-Level Security (RLS)

**What it is:** Multiple organizations (tenants) share the same database, but each can only see their own data.

**Why we need it:** A wedding planner's events and guest lists must be invisible to a corporate travel company on the same platform.

**How we implement it:**
```sql
-- PostgreSQL enforces this at the database level
-- Even if our Python code has a bug and forgets to filter by tenant_id,
-- the database will still block cross-tenant access

ALTER TABLE events ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON events
    USING (tenant_id = current_setting('app.tenant_id')::uuid);
```

**Interview talking point:** "I chose RLS over application-level filtering because it's defense-in-depth. The database is the last line of defense — if our application code has a bug, the data is still isolated."

---

### Concept 2: Pessimistic Locking (SELECT FOR UPDATE)

**What it is:** When two people try to book the same room at the same time, we lock the row so only one transaction can proceed.

**Why we need it:** 200 employees refreshing the booking page at the same time at 10 AM when the event link is shared. Without locking, 10 people could "book" room #50 simultaneously.

**How it works:**
```
Timeline:
  t=0ms    Guest A: SELECT room_block WHERE id=X FOR UPDATE  → Gets lock ✅
  t=5ms    Guest B: SELECT room_block WHERE id=X FOR UPDATE  → WAITS (blocked) ⏳
  t=10ms   Guest A: UPDATE booked_rooms = booked_rooms + 1   → Success
  t=15ms   Guest A: COMMIT                                    → Lock released
  t=16ms   Guest B: SELECT room_block WHERE id=X FOR UPDATE  → Gets lock ✅ (sees updated data)
  t=20ms   Guest B: Check: booked_rooms < total_rooms?        → Still available? Proceed. Full? Waitlist.
```

**Interview talking point:** "I used pessimistic locking instead of optimistic because inventory is a scarce resource with high contention. Optimistic locking would cause too many retries at peak load — SELECT FOR UPDATE guarantees exactly one winner per room."

---

### Concept 3: Event Sourcing (Payment Ledger)

**What it is:** Instead of updating payment records, we append new entries. The current state is derived by reading all entries.

**Why we need it:** Financial data must have a complete audit trail. "The payment was ₹12,000" is less useful than "₹24,000 was debited from corporate wallet, then ₹12,000 was charged to guest's card, then ₹3,000 was refunded due to one-night cancellation."

**How it looks in the data:**
```
PAYMENT_LEDGER for Booking #B123:
┌────┬──────────────────┬──────────┬───────────┬─────────────┐
│ #  │ Type             │ Amount   │ Status    │ Timestamp   │
├────┼──────────────────┼──────────┼───────────┼─────────────┤
│ 1  │ corporate_subsidy│ +₹24,000 │ completed │ Mar 1 10:00 │
│ 2  │ guest_payment    │ +₹12,000 │ pending   │ Mar 1 10:00 │
│ 3  │ guest_payment    │ +₹12,000 │ completed │ Mar 1 10:01 │
│ 4  │ refund           │ -₹4,000  │ completed │ Mar 5 14:30 │
└────┴──────────────────┴──────────┴───────────┴─────────────┘

Current balance: ₹24,000 + ₹12,000 - ₹4,000 = ₹32,000
```

**Interview talking point:** "The payment ledger uses event sourcing — we never mutate financial records, only append. This gives us a complete audit trail and makes the system resilient to partial failures. If the Razorpay callback fails, we still have the 'pending' record."

---

### Concept 4: Pub/Sub Pattern (Redis)

**What it is:** When something happens (a booking, a cancellation), we "publish" a message to a channel. Anyone "subscribed" to that channel receives it instantly.

**Why we need it:** The planner's dashboard needs to update in real-time. When Guest #245 books, the dashboard count should go from 244 → 245 without the planner refreshing.

**How it flows:**
```
Booking created
    │
    ├──→ Redis PUBLISH "event:E1:updates" { type: "new_booking", data: {...} }
    │
    ├──→ WebSocket subscriber (planner's dashboard) receives message
    │    └──→ Frontend updates the count: 244 → 245
    │
    └──→ WebSocket subscriber (hotel admin) receives message
         └──→ Hotel sees "45/100 rooms consumed" → "46/100"
```

**Interview talking point:** "Instead of the dashboard polling the API every 5 seconds (which wastes bandwidth and has latency), I use Redis Pub/Sub with WebSockets for push-based updates. This scales to thousands of concurrent dashboards with minimal server load."

---

### Concept 5: ACID Transactions

**What it is:** Atomicity, Consistency, Isolation, Durability — the four guarantees of a database transaction.

**Why we need it:** The booking + payment flow touches 4 tables in one operation. If the payment fails after the room is marked as booked, we have a corrupted state. ACID ensures either everything succeeds or everything rolls back.

**How it applies to our booking:**
```
BEGIN TRANSACTION;
  1. Lock room_block row                    ← If anything below fails...
  2. Increment booked_rooms                 ← ...this gets rolled back
  3. Create booking record                  ← ...this gets rolled back
  4. Debit corporate wallet                 ← ...this gets rolled back
  5. Create payment_ledger entries           ← ...this gets rolled back
COMMIT;  ← Only now is everything persisted atomically
```

**Interview talking point:** "The booking flow wraps 4 table mutations in a single transaction. If the corporate wallet has insufficient funds at step 4, the entire booking rolls back — the room is never marked as taken, and the guest sees an error, not a corrupted half-booking."

---

### Concept 6: RBAC (Role-Based Access Control)

**What it is:** Different users can do different things based on their role.

**Why we need it:** A planner can create events. A viewer can only see dashboards. A hotel admin can only manage their allotments. A guest can only book rooms.

**The permission matrix:**

```
                    admin   planner   viewer   hotel_admin   guest
create_event          ✅       ✅       ❌         ❌          ❌
manage_blocks         ✅       ✅       ❌         ✅          ❌
view_dashboard        ✅       ✅       ✅         ✅          ❌
manage_wallet         ✅       ❌       ❌         ❌          ❌
import_guests         ✅       ✅       ❌         ❌          ❌
create_booking        ❌       ❌       ❌         ❌          ✅
export_rooming_list   ✅       ✅       ✅         ✅          ❌
```

---

### Concept 7: Task Queues (Celery + Redis)

**What it is:** Offloading slow work (sending emails, processing files, generating reports) to background workers so the API stays fast.

**Why we need it:**

```
WITHOUT task queue:
  POST /api/bookings → Create booking (10ms) → Send email (1500ms) → Response (1510ms)
  User waits 1.5 seconds. Feels slow.

WITH task queue:
  POST /api/bookings → Create booking (10ms) → Queue email task (2ms) → Response (12ms)
  Background worker sends email 3 seconds later. User doesn't wait.
```

**Tasks we run in the background:**
| Task | Trigger | Why Background? |
|------|---------|-----------------|
| Send confirmation email | Booking created | Email APIs are slow (1-2s) |
| Send reminder emails | Scheduled (cron) | Batch job for 500+ guests |
| Release expired blocks | Scheduled (cron) | Runs at midnight, not per-request |
| Process ETL upload | File uploaded | Gemini API call takes 5-10s |
| Generate analytics | Dashboard loaded | Complex queries may take 2-3s |

---

### Concept 8: Hybrid Search (SQL + Vector)

**What it is:** Combining traditional database filtering (exact matches) with AI-powered semantic matching (similar meaning).

**Why we need it:** "Conference hall" should match a venue that has "business center" or "meeting room." SQL LIKE can't do this. But vector search alone is too fuzzy for hard constraints like price or city.

**The hybrid approach:**
```
Step 1 (SQL): Filter by hard constraints → 50 candidates
            WHERE city = 'Goa' AND total_rooms >= 200 AND price <= 12000

Step 2 (Vector): Rank by semantic similarity → reorder the 50
            ORDER BY embedding <=> query_embedding  (cosine similarity)

Step 3 (Composite): Final rank with weighted score
            price_fit × 0.3 + availability × 0.3 + semantic_match × 0.2 + rating × 0.1 + distance × 0.1
```

---

### Concept 9: Database Connection Pooling

**What it is:** Reusing database connections instead of creating a new one for every request.

**Why we need it:** Creating a PostgreSQL connection takes ~50ms. If we have 200 concurrent requests, that's 200 new connections. Connection pooling keeps ~20 connections alive and shares them.

```python
# SQLAlchemy async engine with connection pooling
engine = create_async_engine(
    DATABASE_URL,
    pool_size=20,          # Keep 20 connections alive
    max_overflow=10,       # Allow 10 more during spikes
    pool_timeout=30,       # Wait 30s for a free connection
    pool_recycle=1800,     # Refresh connections every 30 min
)
```

---

### Concept 10: Rate Limiting

**What it is:** Preventing any single client from overwhelming the API with too many requests.

**Why we need it:** Without it, a bot or buggy frontend could send 10,000 booking requests/second and crash the system.

```python
# Rate limiting middleware using Redis
# 100 requests per minute per user
async def rate_limit(request, user_id):
    key = f"rate:{user_id}:{current_minute()}"
    count = await redis.incr(key)
    if count == 1:
        await redis.expire(key, 60)
    if count > 100:
        raise HTTPException(429, "Too many requests")
```

---

## 5. Innovations — What Makes This Special

### Innovation 1: Split-Ledger Payment Engine

**Standard approach:** Pay full amount. Done.
**Our approach:** Dynamically compute who pays what based on corporate subsidy rules, guest category, room type, and wallet balance — in a single ACID transaction with append-only audit trail.

**Why it's innovative:**
- Handles partial subsidies (company pays ₹8K, employee pays ₹4K)
- Category-based rules (VIPs get full subsidy, interns get 50%)
- Real-time wallet balance tracking with concurrent deductions
- Append-only ledger for complete financial audit trail
- Refund handling that reverses only the correct portions

**System design skills demonstrated:** ACID compliance, financial data integrity, event sourcing, concurrent resource management

---

### Innovation 2: Smart Ingestion ETL with LLM

**Standard approach:** Manual data entry or rigid CSV template that must be exact.
**Our approach:** Accept messy real-world files (Excel with merged cells, PDF contracts, inconsistent column names) and use Gemini to extract structured data with a human-in-the-loop validation step.

**Why it's innovative:**
- Real LLM integration that solves a real business problem (not a chatbot)
- Human-in-the-loop: AI extracts, human approves — shows you understand AI isn't perfect
- Handles edge cases: duplicate detection, fuzzy name matching, missing field inference
- One-shot parsing of hotel contracts to extract room types, rates, inclusions

**System design skills demonstrated:** ETL pipelines, data validation, AI integration, batch processing, idempotent operations

---

### Innovation 3: Concurrency-Safe Inventory with Automatic Escalation

**Standard approach:** First-come-first-served with no handling of the "full" case.
**Our approach:** Database-level locking + automatic waitlist enrollment + cascading notification when rooms free up.

**Why it's innovative:**
- The chain: booking → block full → waitlist → cancellation → auto-offer → cascading fill
- This is the exact pattern used by ticketing platforms (BookMyShow, StubHub)
- Zero manual intervention required for the entire lifecycle
- Configurable per-event (some events allow waitlist, some don't)

---

## 6. How It All Connects — End-to-End Flows

### Flow 1: Planner Creates an Event (Day 1)

```
Planner → POST /api/v1/venues/search
        → "200-person offsite in Goa, March, conference hall"
        → Returns: 8 ranked venues
        
Planner → POST /api/v1/events
        → Creates "Annual Offsite 2026" with category rules
        
Planner → POST /api/v1/events/{id}/blocks
        → Creates room block: 100 standard rooms @ ₹10K, 20 suites @ ₹18K
        
Planner → POST /api/v1/events/{id}/guests/import
        → Uploads employee_list.xlsx (500 rows)
        → ETL pipeline: parse → extract → validate → review → insert
        
Planner → POST /api/v1/events/{id}/microsite
        → Auto-generates branded booking page at /event/annual-offsite-2026
        
System  → Celery task: sends 500 invitation emails with unique booking links
```

### Flow 2: Guest Books a Room (Day 5)

```
Guest   → GET /event/annual-offsite-2026?token=abc123
        → Sees: event details, itinerary, available room types (filtered by their category)
        
Guest   → POST /api/v1/bookings {room_block_id, token, check_in, check_out}
        → Backend: acquire lock → check availability → calculate split payment
        → Corporate wallet debited ₹30K (₹10K × 3 nights)
        → Guest charged ₹0 (fully subsidized for "employee" category)
        → Booking confirmed
        
System  → Redis PUBLISH → Planner's dashboard updates: 156 → 157 booked
System  → Celery task: sends confirmation email with QR code and itinerary
```

### Flow 3: Room Block Fills Up, Waitlist Kicks In (Day 10)

```
Guest Z → POST /api/v1/bookings {room_block_id: standard_block}
        → Backend: acquire lock → booked_rooms (100) == total_rooms (100) → FULL
        → Auto-add to waitlist (position #4)
        → Return: "Waitlisted. You'll be notified if a room becomes available."
        → Redis PUBLISH → Dashboard: "23 on waitlist for standard rooms"
```

### Flow 4: Cancellation Triggers Waitlist Cascade (Day 12)

```
Guest A → DELETE /api/v1/bookings/{id}
        → Backend: mark cancelled → decrement block → refund initiated
        → Check waitlist → Guest at position #1 notified
        → Email: "A standard room is now available! Book within 24 hours."
        → Redis PUBLISH → Dashboard: 100 → 99 booked, waitlist: 23 → 22
```

### Flow 5: Deadline Reached, Auto-Release (Day 20)

```
System  → Celery cron job at midnight → checks all blocks with deadline = today
        → Standard block: 85/100 booked, 15 unclaimed
        → Auto-release 15 rooms back to hotel inventory
        → Email to planner: "15 rooms released. Final count: 85 standard rooms."
        → Email to hotel: "15 rooms returned to your general inventory."
        → Block status: active → released
```

---

> [!TIP]
> **Next step:** With this understanding solid, we should start building the **database layer first** (PostgreSQL schema + models), then the **auth module**, then the **event + inventory modules**. This is the foundation everything else depends on. Ready to start coding?
