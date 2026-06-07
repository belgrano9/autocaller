import csv
from pathlib import Path

from fastapi import APIRouter

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


def load_venues():
    with open(CSV_PATH, encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


@router.get("")
def list_venues(region: str | None = None):
    rows = load_venues()
    venues = []
    for i, r in enumerate(rows, 1):
        if region and region.lower() not in r["region"].lower():
            continue
        verified = r.get("email_verified", "")
        accepts  = verified in ("smtp_ok", "mx_ok", "smtp_unknown") and bool(r["email"])
        venues.append({
            "id":               i,
            "name":             r["name"],
            "city":             r["city"],
            "department":       r["department"],
            "region":           r["region"],
            "email":            r["email"] or None,
            "accepts_email":    accepts,
            "contact_method":   CONTACT_MAP.get(r["contact_type"], r["contact_type"]),
            "website_url":      r["website"] or None,
            "price_tier":       None,
            "base_price_cents": None,
            "style_tags":       [r["type"]] if r.get("type") else None,
        })
    return venues
