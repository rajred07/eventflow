"""
Seed Data — populates the database with demo venues for testing.

Run with: uv run python -m app.db.seed
"""

import asyncio

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import Base
from app.db.session import async_session, engine
from app.models.venue import Venue


DEMO_VENUES = [
    {
        "name": "Taj Exotica Resort & Spa",
        "city": "Goa",
        "state": "Goa",
        "address": "Calangute, North Goa",
        "latitude": 15.5449,
        "longitude": 73.7554,
        "total_rooms": 140,
        "max_event_capacity": 500,
        "star_rating": 5.0,
        "user_rating": 4.7,
        "description": "Luxury beachfront resort with Mediterranean-style architecture, world-class spa, and multiple event venues including grand ballroom and oceanview terrace.",
        "amenities": ["conference_hall", "ballroom", "pool", "spa", "beach", "wifi", "airport_shuttle", "business_center", "gym", "restaurant"],
        "pricing_tiers": {"standard": 9500, "deluxe": 14000, "suite": 25000},
        "contact_email": "events@tajgoa.com",
        "contact_phone": "+91-832-6633333",
    },
    {
        "name": "ITC Grand Chola",
        "city": "Chennai",
        "state": "Tamil Nadu",
        "address": "Mount Road, Guindy, Chennai",
        "latitude": 13.0108,
        "longitude": 80.2207,
        "total_rooms": 600,
        "max_event_capacity": 3000,
        "star_rating": 5.0,
        "user_rating": 4.8,
        "description": "India's largest luxury hotel with 78,000 sq ft of event space. Palatial Dravidian architecture with 10 restaurants, rooftop infinity pool, and state-of-the-art conference center.",
        "amenities": ["conference_hall", "ballroom", "pool", "spa", "wifi", "business_center", "gym", "restaurant", "rooftop_venue", "valet_parking"],
        "pricing_tiers": {"standard": 8000, "deluxe": 12000, "suite": 22000},
        "contact_email": "mice@itchotels.com",
        "contact_phone": "+91-44-22200000",
    },
    {
        "name": "The Leela Palace",
        "city": "Udaipur",
        "state": "Rajasthan",
        "address": "Lake Pichola, Udaipur",
        "latitude": 24.5672,
        "longitude": 73.6812,
        "total_rooms": 80,
        "max_event_capacity": 300,
        "star_rating": 5.0,
        "user_rating": 4.9,
        "description": "Palatial lakeside luxury hotel with stunning Lake Pichola views. Perfect for royal destination weddings and intimate corporate retreats with Mewar-inspired architecture.",
        "amenities": ["ballroom", "pool", "spa", "lake_view", "wifi", "helipad", "boat_service", "restaurant", "terrace_dining", "cultural_performances"],
        "pricing_tiers": {"deluxe": 18000, "suite": 35000, "royal_suite": 75000},
        "contact_email": "weddings@theleela.com",
        "contact_phone": "+91-294-6701234",
    },
    {
        "name": "JW Marriott Resort",
        "city": "Jaipur",
        "state": "Rajasthan",
        "address": "Ajmer Road, Jaipur",
        "latitude": 26.8478,
        "longitude": 75.7578,
        "total_rooms": 200,
        "max_event_capacity": 1000,
        "star_rating": 5.0,
        "user_rating": 4.6,
        "description": "Sprawling resort with Mughal-inspired gardens, 14 acres of event lawns, and modern conference facilities. Popular for large corporate conferences and grand weddings.",
        "amenities": ["conference_hall", "ballroom", "pool", "spa", "lawn", "wifi", "airport_shuttle", "business_center", "gym", "restaurant", "kids_area"],
        "pricing_tiers": {"standard": 7500, "deluxe": 11000, "suite": 20000},
        "contact_email": "events@jwmarriotjaipur.com",
        "contact_phone": "+91-141-6777777",
    },
    {
        "name": "Radisson Blu Resort",
        "city": "Goa",
        "state": "Goa",
        "address": "Cavelossim Beach, South Goa",
        "latitude": 15.1578,
        "longitude": 73.9368,
        "total_rooms": 180,
        "max_event_capacity": 600,
        "star_rating": 4.5,
        "user_rating": 4.4,
        "description": "Beachfront resort with panoramic Arabian Sea views, 5 outdoor event spaces, and a dedicated MICE wing with 3 conference rooms.",
        "amenities": ["conference_hall", "pool", "beach", "spa", "wifi", "business_center", "gym", "restaurant", "water_sports"],
        "pricing_tiers": {"standard": 6000, "deluxe": 9000, "suite": 16000},
        "contact_email": "events@radissongoa.com",
        "contact_phone": "+91-832-6726726",
    },
    {
        "name": "Hyatt Regency",
        "city": "Delhi",
        "state": "Delhi",
        "address": "Bhikaji Cama Place, Ring Road, New Delhi",
        "latitude": 28.5695,
        "longitude": 77.1882,
        "total_rooms": 507,
        "max_event_capacity": 2000,
        "star_rating": 5.0,
        "user_rating": 4.5,
        "description": "Centrally located luxury hotel with extensive MICE infrastructure. Features The Mansion — a 12,000 sq ft pillarless ballroom — and 9 modular meeting rooms.",
        "amenities": ["conference_hall", "ballroom", "pool", "spa", "wifi", "business_center", "gym", "restaurant", "concierge", "valet_parking"],
        "pricing_tiers": {"standard": 7000, "deluxe": 10500, "suite": 18000},
        "contact_email": "mice@hyattdelhi.com",
        "contact_phone": "+91-11-26791234",
    },
    {
        "name": "Vivanta by Taj",
        "city": "Coorg",
        "state": "Karnataka",
        "address": "Galibeedu Post, Madikeri, Coorg",
        "latitude": 12.4244,
        "longitude": 75.7382,
        "total_rooms": 96,
        "max_event_capacity": 200,
        "star_rating": 4.5,
        "user_rating": 4.6,
        "description": "Hillside retreat surrounded by 180 acres of coffee and spice plantations. Ideal for intimate corporate offsites and team-building retreats with adventure activities.",
        "amenities": ["conference_hall", "pool", "spa", "nature_trails", "wifi", "adventure_sports", "coffee_tour", "bonfire_area", "restaurant"],
        "pricing_tiers": {"standard": 8000, "deluxe": 12000, "suite": 20000},
        "contact_email": "events@vivantacoorg.com",
        "contact_phone": "+91-8272-265000",
    },
    {
        "name": "The Oberoi Amarvilas",
        "city": "Agra",
        "state": "Uttar Pradesh",
        "address": "Taj East Gate Road, Agra",
        "latitude": 27.1689,
        "longitude": 78.0455,
        "total_rooms": 102,
        "max_event_capacity": 250,
        "star_rating": 5.0,
        "user_rating": 4.9,
        "description": "Ultra-luxury hotel with unobstructed Taj Mahal views from every room. Mughal-inspired gardens and terraces create a magical setting for premium destination weddings.",
        "amenities": ["ballroom", "pool", "spa", "taj_view", "wifi", "butler_service", "restaurant", "terrace_dining", "cultural_experiences"],
        "pricing_tiers": {"deluxe": 28000, "premier": 38000, "suite": 65000},
        "contact_email": "weddings@oberoiamarvilas.com",
        "contact_phone": "+91-562-2231515",
    },
]


async def seed_venues():
    """Insert demo venues if the venues table is empty."""
    async with async_session() as db:
        # Check if venues already exist
        result = await db.execute(select(Venue).limit(1))
        if result.scalar_one_or_none():
            print("ℹ️  Venues already seeded, skipping.")
            return

        for venue_data in DEMO_VENUES:
            venue = Venue(**venue_data)
            db.add(venue)

        await db.commit()
        print(f"✅ Seeded {len(DEMO_VENUES)} demo venues")


async def main():
    """Run seed from command line."""
    await seed_venues()


if __name__ == "__main__":
    asyncio.run(main())
