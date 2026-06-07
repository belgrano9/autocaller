"""
Seed script: load the initial Île-de-France venue catalogue.
Run once after migrations: uv run python db/seed_venues.py
"""

import asyncio

from app.db import AsyncSessionLocal
from app.models.venue import Venue

VENUES = [
    {
        "name": "Château de Santeny",
        "email": "contact@chateaudesanteny.fr",
        "accepts_email": True,
        "contact_method": "email",
        "website_url": "https://www.chateaudesanteny.fr",
        "region": "Île-de-France",
        "department": "94",
        "city": "Santeny",
        "capacity_min": 50,
        "capacity_max": 150,
        "style_tags": ["château", "classique"],
        "price_tier": "mid",
        "active": True,
    },
    {
        "name": "Domaine de la Vallée Aux Pages",
        "email": "contact@vallee-aux-pages.com",
        "accepts_email": True,
        "contact_method": "email",
        "website_url": "https://www.vallee-aux-pages.com",
        "region": "Île-de-France",
        "department": "78",
        "city": "Paray-Douaville",
        "capacity_min": 50,
        "capacity_max": 200,
        "style_tags": ["domaine", "champêtre"],
        "price_tier": "mid",
        "active": True,
    },
    {
        "name": "La Ferme de l'Avenir",
        "email": "contact@lafermedelavenir.com",
        "accepts_email": True,
        "contact_method": "email",
        "website_url": "https://lafermedelavenir.com",
        "region": "Île-de-France",
        "department": "77",
        "city": "Gironville",
        "capacity_min": 30,
        "capacity_max": 120,
        "style_tags": ["ferme", "rustique", "champêtre"],
        "price_tier": "mid",
        "active": True,
    },
    {
        "name": "Domaine de Mauvoisin",
        "email": "contact@mauvoisin.com",
        "accepts_email": True,
        "contact_method": "email",
        "website_url": "https://mauvoisin.fr",
        "region": "Île-de-France",
        "department": "78",
        "city": "Lommoye",
        "capacity_min": 80,
        "capacity_max": 200,
        "style_tags": ["domaine", "château", "premium"],
        "price_tier": "premium",
        "active": True,
    },
    {
        "name": "Château de Séréville",
        "email": "contact@chateaudesereville.com",
        "accepts_email": True,
        "contact_method": "email",
        "website_url": "https://www.chateaudesereville.com",
        "region": "Île-de-France",
        "department": "77",
        "city": "Séréville",
        "capacity_min": 50,
        "capacity_max": 200,
        "style_tags": ["château", "forêt", "hébergement"],
        "price_tier": "premium",
        "active": True,
    },
    {
        "name": "Château de Janvry",
        "email": "contact@chateaudejanvry.com",
        "accepts_email": True,
        "contact_method": "email",
        "website_url": "https://www.chateaudejanvry.com",
        "region": "Île-de-France",
        "department": "91",
        "city": "Janvry",
        "capacity_min": 50,
        "capacity_max": 150,
        "style_tags": ["château", "Essonne"],
        "price_tier": "mid",
        "active": True,
    },
    # Form-only venues (inactive for email MVP, available for discovery)
    {
        "name": "Château de Villette",
        "email": None,
        "accepts_email": False,
        "contact_method": "form_only",
        "website_url": "https://www.mariages.net/chateau-mariage/chateau-de-villette",
        "region": "Île-de-France",
        "department": "95",
        "city": "Condécourt",
        "capacity_min": 100,
        "capacity_max": 250,
        "style_tags": ["château", "luxe"],
        "price_tier": "premium",
        "active": True,
    },
    {
        "name": "Domaine du Marais",
        "email": None,
        "accepts_email": False,
        "contact_method": "phone_only",
        "website_url": "https://domainedumarais91.fr",
        "region": "Île-de-France",
        "department": "91",
        "city": "Maisse",
        "capacity_min": 50,
        "capacity_max": 180,
        "style_tags": ["domaine", "Essonne"],
        "price_tier": "mid",
        "active": True,
    },
]


async def main() -> None:
    async with AsyncSessionLocal() as db:
        for data in VENUES:
            venue = Venue(**data)
            db.add(venue)
        await db.commit()
    print(f"Seeded {len(VENUES)} venues.")


if __name__ == "__main__":
    asyncio.run(main())
