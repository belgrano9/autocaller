# Autocaller — Devis Mariages

A lightweight, database-free web application designed to catalog wedding venues and automate outreach emails to request quotes.

## Current Architecture

```
                                    ┌───────────────────────┐
                                    │    Frontend (Vite)    │
                                    │  (HTML/CSS/VanillaJS) │
                                    └───────────┬───────────┘
                                                │
                                       HTTP API │ /api/...
                                                ▼
                                    ┌───────────────────────┐
                                    │   FastAPI Backend     │
                                    └─────┬───────────┬─────┘
                                          │           │
                     Reads local database │           │ Sends SMTP emails
                                          ▼           ▼
                                    ┌───────────┐ ┌───────────┐
                                    │venues.csv │ │Gmail/Brevo│
                                    └───────────┘ └───────────┘
```

### 1. Data Store
All wedding venues are stored in a local flat CSV file: [venues.csv](file:///e:/workspace/autocaller/venues.csv).
*   **Columns**: `name`, `city`, `department`, `region`, `type`, `website`, `email`, `phone`, `contact_type`, `email_verified`
*   **Email Verification**: The [verify_emails.py](file:///e:/workspace/autocaller/scripts/verify_emails.py) script can be run locally to verify emails via DNS and SMTP handshakes.

### 2. Dual-Mode SMTP Dispatcher
Emails are sent directly from the FastAPI backend depending on the runtime mode:
*   **DEV Mode**: Sends via personal Gmail SMTP.
*   **INT Mode**: Sends via Brevo SMTP (transactional provider).

---

## Finalized Outreach Flow & Logic

Following the `/grill-me` alignment, the system will operate under these specifications:

### 1. Global "Wedding Project" State (Client-Side)
*   At the top of the dashboard, a **"Wedding Project" settings card** allows the user to input:
    *   `couple_name` (e.g. "Alice & Bob")
    *   `event_date` (e.g. "15/09/2026")
    *   `guest_count` (e.g. "120")
    *   `budget` (e.g. "15 000 €")
    *   `notes` (optional custom message)
*   These details are automatically saved in browser `localStorage`.
*   A **Status Summary** displays how many venues have been contacted (saved in `localStorage` as well).

### 2. Live Email Preview Modal
*   When a user clicks **"Contacter"** next to a venue:
    *   The frontend calls the backend preview endpoint `/api/outreach/preview`.
    *   The backend renders the `outreach.html` template using the couple's input data.
    *   A beautiful modal opens showing the **live HTML email preview** so the user sees exactly what will be sent.
    *   The modal has two buttons: **"Envoyer"** (Send) and **"Annuler"** (Cancel).

### 3. Email Dispatch Routing (DEV vs. INT Safety)
*   When the user confirms the send:
    *   The frontend calls the backend send endpoint `/api/outreach/send`.
    *   **DEV Mode**: Redirects the email to `test_email` (defined in `.env`). It does *not* email the venue.
    *   **INT Mode**: Sends the email directly to the venue's email address listed in `venues.csv`.
    *   On success, the venue is marked as "Contacted ✓" in `localStorage` and the UI updates immediately.

### 4. API Endpoints (Backend)
*   `GET /api/venues`: Loads venues from `venues.csv` (already implemented).
*   `GET /api/mode` & `POST /api/mode/{mode}`: Toggles dev/int SMTP modes (already implemented).
*   `POST /api/outreach/preview`: Takes wedding details + venue name, renders and returns the HTML preview.
*   `POST /api/outreach/send`: Takes wedding details + venue name + venue email. Performs the SMTP send according to the current mode.
