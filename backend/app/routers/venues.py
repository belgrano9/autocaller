import csv
from pathlib import Path

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(prefix="/venues", tags=["venues"])

CSV_PATH = Path(__file__).parent.parent.parent.parent / "venues.csv"

CONTACT_MAP = {
    "email+phone": "email",
    "email+form":  "email",
    "email":       "email",
    "phone+form":  "form_only",
    "form":        "form_only",
    "phone":       "phone_only",
}


class VenueCard(BaseModel):
    """Canonical venue card contract consumed by the dashboard grid."""

    id: int
    name: str
    city: str
    department: str
    region: str
    venue_type: str
    style_tags: list[str] | None
    photo_url: str | None
    email: str | None
    phone: str | None
    accepts_email: bool
    email_verified: str
    contact_method: str
    website_url: str | None
    estimated_price: str | None = None


def load_venues():
    with open(CSV_PATH, encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


@router.get("", response_model=list[VenueCard])
def list_venues(region: str | None = None):
    rows = load_venues()
    venues = []
    for i, r in enumerate(rows, 1):
        if region and region.lower() not in r["region"].lower():
            continue
        verified = r.get("email_verified", "")
        accepts  = verified in ("smtp_ok", "mx_ok", "smtp_unknown") and bool(r["email"])
        venues.append(VenueCard(
            id=i,
            name=r["name"],
            city=r["city"],
            department=r["department"],
            region=r["region"],
            venue_type=r.get("type", ""),
            style_tags=[r["type"]] if r.get("type") else None,
            photo_url=r.get("photo_url") or None,
            email=r["email"] or None,
            phone=r.get("phone") or None,
            accepts_email=accepts,
            email_verified=verified,
            contact_method=CONTACT_MAP.get(r["contact_type"], r["contact_type"]),
            website_url=r["website"] or None,
            estimated_price=None,
        ))
    return venues
