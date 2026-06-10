# Devis Mariages — Roadmap

Agreed product order. Status as of 2026-06-10.

## 1. Venue expansion (France-wide) — _seeder done, enrichment pending_
- Seeder built: `scripts/seed_venues.py` (grounded Gemini + Playwright validation). 100 venues seeded across Normandie / PACA / Centre-Val de Loire / Nouvelle-Aquitaine.
- **Pending:** enrich the 100 new rows — `scrape_contacts.py` → `verify_emails.py` → `scrape_photos.py` (run manually).
- Regions still to seed: Bretagne, Pays de la Loire, Occitanie, Auvergne-Rhône-Alpes, Grand Est, Hauts-de-France, Bourgogne-Franche-Comté.

## 2. Hexmap improvements — ✅ done
Click-any-region drill-down zoom, venue-density shading, hover tooltips.

## 3. Pricing tiers + Stripe — ✅ implemented, live Stripe verification pending
- 3 tiers, monthly subscriptions: **Découverte** (free, 3 sends lifetime) · **Plus** (€9/mo, 15 sends/month) · **Conciergerie** (€19/mo, unlimited). Sends are the paywall.
- Built: billing data model + `quote_sends` log, `services/plans.py` (limits/quota), auth-gated send-cap enforcement on `/api/outreach/send`, `routers/billing.py` (Checkout + portal + webhook), plan/quota in profile, pricing modal + nav badge in `index.html`.
- **Pending:** live test-mode click-through — see `STRIPE_SETUP.md` (needs real `sk_test`, two `price_…`, `whsec_`).

## 4. Conciergerie inbox (top tier) — ⏭ next
Route venue replies via the `devis+{couple}@domain` Reply-To alias + the webhook scaffolding in `backend/app/services/email_provider.py` into the user's in-app inbox. This is the "Bientôt" item already advertised on the Conciergerie tier.

## 5. Anonymous price estimates
Interpolated from quotes collected via the conciergerie (#4). Fills the `estimated_price` stub in the `VenueCard` contract — public (SEO / lead-gen for anonymous visitors), **not** a paid gate.
> Key decision: price data comes from real user quotes via the conciergerie, **not** mass test-emails (deliverability + French deceptive-practice risk).

## 6. Deferred
Venue partnerships / promoted listings, wedding-planner packages, About-page copy.

---
**#4 and #5 are coupled** — the inbox must collect real quote data before estimates have anything to interpolate, so #4 comes first.
