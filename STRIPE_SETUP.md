# Stripe live (test-mode) setup & verification

Step-by-step to wire and exercise the subscription billing added in roadmap item #3
(tiers: Découverte / Plus €9-mo / Conciergerie €19-mo). All in **Stripe Test mode** —
no real money, no real venue emails (keep `APP_MODE=dev`, which redirects mail to `TEST_EMAIL`).

> Secrets go in `backend/.env` only (gitignored). Never commit real keys.

---

## Values to gather (fill these in)

| Env var | Where to get it | Value |
|---|---|---|
| `STRIPE_SECRET_KEY` | Dashboard → Developers → API keys → **Secret key** | `sk_test_…` |
| `STRIPE_PRICE_PLUS` | Product catalog → *Devis Mariages Plus* → Pricing → the **`price_…`** ID | `price_…` |
| `STRIPE_PRICE_CONCIERGERIE` | Product catalog → *Devis Mariages Conciergerie* → Pricing → the **`price_…`** ID | `price_…` |
| `STRIPE_WEBHOOK_SECRET` | printed by `stripe listen` (step 6) | `whsec_…` |
| `APP_BASE_URL` | already set | `http://localhost:8000` |

Products created so far (test mode):
- Plus → product `prod_UgChbsQaOeHstP` *(need its `price_…`, not the `prod_…`)*
- Conciergerie → product `prod_UgChYuKkxVqKgA` *(need its `price_…`)*

Product descriptions (marketing copy only — do not affect billing):
- **Plus** — Jusqu'à 15 demandes de devis par mois, plus comparaison et export des devis.
- **Conciergerie** — Demandes de devis illimitées, comparaison/export, et messagerie conciergerie intégrée.

---

## Steps

### 0. Install the Stripe CLI
```powershell
winget install Stripe.StripeCLI
```
Close and reopen the terminal so `stripe` is on `PATH`.

### 1. Stripe account → Test mode
Log in at https://dashboard.stripe.com and toggle **Test mode** ON (top-right). Everything below is in Test mode.

### 2. Secret key
Developers → API keys → copy the **Secret key** (`sk_test_…`) → `STRIPE_SECRET_KEY`.

### 3. Create the two recurring prices
Product catalog → **+ Add product**, twice:
- **Devis Mariages Plus** — price **€9**, recurring **Monthly** → save → copy the **`price_…`** ID → `STRIPE_PRICE_PLUS`.
- **Devis Mariages Conciergerie** — price **€19**, recurring **Monthly** → save → copy the **`price_…`** ID → `STRIPE_PRICE_CONCIERGERIE`.

### 4. Enable the customer portal *(easy to miss)*
Settings → Billing → **Customer portal** → **Activate**. Required, or the "Gérer l'abonnement" / cancel button throws "configuration not found".

### 5. Log in the CLI
```
stripe login
```
Approve in the browser.

### 6. Start the webhook forwarder (leave running, separate terminal)
```powershell
stripe listen --forward-to localhost:8000/api/billing/webhook
```
Copy the printed `whsec_…` → `STRIPE_WEBHOOK_SECRET`. Keep this terminal open.

### 7. Fill `backend/.env`
```
STRIPE_SECRET_KEY=sk_test_...
STRIPE_WEBHOOK_SECRET=whsec_...
STRIPE_PRICE_PLUS=price_...
STRIPE_PRICE_CONCIERGERIE=price_...
APP_BASE_URL=http://localhost:8000
```

### 8. Start the backend (separate terminal)
```powershell
cd backend; uv run uvicorn app.main:app
```
Restart this whenever `.env` changes (keys load at startup).

### 9. Click-through
1. Open http://localhost:8000/dashboard — register / log in.
2. **Cap:** send 3 quote requests → the 4th opens the pricing modal (HTTP 402).
3. **Plus → Choisir** → Stripe Checkout. Test card `4242 4242 4242 4242`, expiry any future (`12/34`), CVC `123`, any name/email/postal.
4. Pay → "Subscription activated" alert; `stripe listen` logs `checkout.session.completed` + `customer.subscription.created`; nav badge flips to **Plus** after the ~2.5s profile refetch.
5. **Unlock:** sending works past the old cap.
6. **Cancel/swap:** reopen the pricing modal → on a paid plan the other tiers show **Gérer l'abonnement** → portal → cancel → `customer.subscription.deleted` → badge returns to **Découverte**.

---

## Troubleshooting
- `stripe listen` shows **`[400]`** on events → the `whsec_` in `.env` doesn't match the running `stripe listen`; recopy it and restart uvicorn.
- Portal button errors "No configuration provided" → do **step 4** (activate the customer portal in test mode).
- Checkout rejects the price → you pasted a `prod_…` instead of a `price_…`.
- Plan badge doesn't update → webhook didn't reach the app; check the `stripe listen` terminal is running and forwarding to `/api/billing/webhook`.
