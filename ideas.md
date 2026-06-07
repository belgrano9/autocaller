# Ideas

## Future domains of expansion

The current MVP targets wedding venues (Devis Mariages), but the core mechanic —
browse a list of providers, send them an outreach/quote-request email on behalf
of a customer — generalizes to any market where people need quotes from multiple
providers before choosing one. Candidate domains:

- **Construction & home services**: plumbers, electricians, roofers, painters,
  general contractors — people routinely want quotes from 3-5 tradespeople
  before picking one.
- **Legal services**: lawyers (divorce, real estate, business formation) — people
  often shop around for consultations/quotes before committing.
- **Small retail suppliers**: suppliers of food, newspapers, magazines, and goods for small local shops (e.g. convenience stores, grocery stores, newsagents) looking to compare wholesale quotes or establish delivery agreements.

Each domain would need its own outreach template (tone, required details) and
its own provider directory (equivalent of `venues.csv`), but the contact/send
pipeline, mode toggle, and frontend shell could likely be reused largely as-is.

## Monetization: recurring revenue vs. one-time payment

A one-off lump sum (e.g. "pay once to get quotes for your wedding venue") caps
revenue per customer at a single transaction — most users only need the service
once for their event. Ideas for what would make people keep paying:

- **Subscription for ongoing/ recurring needs**: domains where the need recurs
  naturally (e.g. a homeowner needing different tradespeople over time —
  plumber this month, electrician next year) lend themselves to a "quote
  concierge" subscription rather than a single-use purchase.
- **Per-project vs. per-account pricing**: charge per quote-request "project"
  (natural for weddings/one-off events) but bundle/discount for accounts that
  run multiple projects (construction firms requesting quotes from
  subcontractors repeatedly, property managers, etc.).
- **B2B angle**: sell to businesses that repeatedly need quotes from a panel of
  providers (e.g. property managers sourcing contractors, wedding planners
  sourcing venues for multiple clients) — these have ongoing demand and budget,
  unlike individual consumers who use the service once.
- **Value-added recurring features**: things a one-time quote-fetch doesn't
  cover but a subscriber would pay monthly for — e.g. negotiation assistance,
  contract/quote comparison & analysis, reminders/follow-ups with providers,
  saved provider lists, post-purchase support.
