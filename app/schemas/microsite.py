from typing import List, Optional
from uuid import UUID
from decimal import Decimal
from pydantic import BaseModel, Field

# ----------------------------------------
# Models for the Planner (Admin API)
# ----------------------------------------

class MicrositeCreate(BaseModel):
    slug: str = Field(..., description="Unique URL slug (e.g., e2e-offsite-2026)")
    theme_color: Optional[str] = Field("#c29b40", description="Hex accent color code")
    hero_image_url: Optional[str] = None
    tagline: Optional[str] = Field(None, description="Sub-headline shown on the hero, e.g. 'THE CURATED SANCTUARY'")
    welcome_message: Optional[str] = None
    support_email: Optional[str] = None
    support_phone: Optional[str] = None
    is_published: bool = True

class MicrositeUpdate(BaseModel):
    slug: Optional[str] = None
    theme_color: Optional[str] = None
    hero_image_url: Optional[str] = None
    tagline: Optional[str] = None
    welcome_message: Optional[str] = None
    support_email: Optional[str] = None
    support_phone: Optional[str] = None
    is_published: Optional[bool] = None

class MicrositeResponse(BaseModel):
    id: UUID
    tenant_id: UUID
    event_id: UUID
    slug: str
    theme_color: str
    hero_image_url: Optional[str]
    tagline: Optional[str]
    welcome_message: Optional[str]
    support_email: Optional[str]
    support_phone: Optional[str]
    is_published: bool

    class Config:
        from_attributes = True

# ----------------------------------------
# Models for the Guest (Public API)
# ----------------------------------------

class PublicEventDetailsResponse(BaseModel):
    """The generic details returned to the frontend when a valid guest asks for the page payload."""
    event_name: str
    destination: Optional[str]
    start_date: str
    end_date: str
    description: Optional[str]
    guest_name: str
    guest_category: str
    microsite_theme_color: str
    microsite_hero_image_url: Optional[str]
    microsite_tagline: Optional[str]
    microsite_welcome_message: Optional[str]
    microsite_support_email: Optional[str]
    microsite_support_phone: Optional[str]


class PublicRoomOption(BaseModel):
    """A room option conditionally rendered for a guest based on their category"""
    room_block_id: UUID
    room_type: str
    negotiated_rate: float
    corporate_subsidy: float
    amount_due: float
    available_rooms: int

class PublicRoomOptionsPayload(BaseModel):
    options: List[PublicRoomOption]
