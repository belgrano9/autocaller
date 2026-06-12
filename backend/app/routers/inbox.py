"""
Conciergerie inbox (roadmap #4) — the inbound half of the devis conversation.

A venue's reply lands on devis+{token}@{reply_to_domain}, whose MX points at
Brevo inbound parsing; Brevo POSTs the parsed message to `POST /api/inbox/webhook`.
We extract the routing token from the recipient address, map it back to the
conversation opened at send time, and append an inbound message to the thread.

Brevo does not HMAC-sign its inbound webhook, so it is authenticated by an
unguessable secret in the configured URL (?secret=...) plus the requirement that
the token resolve to a real conversation; anything else is dropped.

Endpoints:
  POST /api/inbox/webhook         public; Brevo inbound parsing target
  GET  /api/inbox                 auth; the user's conversation threads
  GET  /api/inbox/{id}            auth; one thread with its messages
  POST /api/inbox/{id}/reply      auth; reply to the venue, threaded
  POST /api/inbox/_simulate       dev-only; inject a fake inbound reply (no DNS)
"""

import hmac
import re

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

import app.services.email_provider as provider
from app import db
from app.config import settings
from app.routers.auth import authenticate_session
from app.services.email_provider import build_reply_to, send_email

router = APIRouter(prefix="/inbox", tags=["inbox"])

# devis+{token}@domain  →  token
_TOKEN_RE = re.compile(r"devis\+([^@]+)@", re.IGNORECASE)

# Lines at/after which an inbound reply is just the quoted history we sent —
# used only as a fallback when the provider hasn't already extracted the new text.
_QUOTE_MARKERS = [
    re.compile(r"^>"),                                    # quoted lines
    re.compile(r"^\s*Le .+ a (?:é|e)crit\s*:", re.I),     # FR: "Le ... a écrit :"
    re.compile(r"^\s*On .+ wrote\s*:", re.I),             # EN: "On ... wrote:"
    re.compile(r"^-{2,}\s*Original Message", re.I),
    re.compile(r"^_{5,}$"),                               # Outlook divider
    re.compile(r"^\s*De\s*:\s", re.I),                    # FR forwarded header block
    re.compile(r"^\s*From\s*:\s", re.I),                  # EN forwarded header block
]


def _strip_quoted(text: str) -> str:
    """Best-effort: keep only the reply, dropping the quoted message below it."""
    out = []
    for line in text.splitlines():
        if any(m.search(line) for m in _QUOTE_MARKERS):
            break
        out.append(line)
    return "\n".join(out).strip() or text.strip()


def _extract_token(address: str | None) -> str | None:
    if not address:
        return None
    m = _TOKEN_RE.search(address)
    return m.group(1) if m else None


def _store_inbound(
    token: str | None,
    *,
    from_addr: str | None,
    to_addr: str | None,
    subject: str | None,
    body_text: str | None,
    body_html: str | None,
    raw_ref: str | None,
) -> bool:
    """Routes one inbound message to its thread. Returns True if it matched a
    conversation; unknown tokens are silently dropped (spam / stale aliases)."""
    if not token:
        return False
    convo = db.get_conversation_by_token(token)
    if not convo:
        return False
    db.add_message(
        convo["id"],
        "in",
        from_addr=from_addr,
        to_addr=to_addr,
        subject=subject,
        body_text=body_text,
        body_html=body_html,
        raw_ref=raw_ref,
    )
    return True


def _ingest_brevo_item(item: dict) -> bool:
    """Maps one Brevo inbound-parsing item onto an inbound message."""
    # Recipient carrying our token may be in To or Cc; find the first match.
    token = None
    for field in ("To", "Cc"):
        for rcpt in item.get(field) or []:
            token = _extract_token(rcpt.get("Address") if isinstance(rcpt, dict) else rcpt)
            if token:
                break
        if token:
            break

    sender = item.get("From") or {}
    from_addr = sender.get("Address") if isinstance(sender, dict) else sender

    # Brevo pre-extracts the new reply (sans quoted history); fall back to our
    # own stripping of the raw text if that field is absent.
    body_text = item.get("ExtractedMarkdownMessage")
    if not body_text:
        raw = item.get("RawTextBody") or ""
        body_text = _strip_quoted(raw) if raw else None

    return _store_inbound(
        token,
        from_addr=from_addr,
        to_addr=None,
        subject=item.get("Subject"),
        body_text=body_text,
        body_html=item.get("RawHtmlBody"),
        raw_ref=item.get("MessageId"),
    )


@router.post("/webhook")
async def inbound_webhook(request: Request, secret: str = ""):
    """Brevo inbound-parsing target. Authenticated by the URL secret + token lookup."""
    expected = settings.inbound_webhook_secret
    if not expected or not hmac.compare_digest(secret, expected):
        raise HTTPException(status_code=403, detail="invalid webhook secret")
    payload = await request.json()
    items = payload.get("items") if isinstance(payload, dict) else None
    if not items:
        return {"received": 0, "matched": 0}
    matched = sum(1 for item in items if _ingest_brevo_item(item))
    return {"received": len(items), "matched": matched}


@router.get("")
def list_inbox(user: dict = Depends(authenticate_session)):
    """The user's conversation threads, most-recently-active first."""
    return {"conversations": db.list_conversations(user["email"])}


@router.get("/{conversation_id}")
def get_thread(conversation_id: int, user: dict = Depends(authenticate_session)):
    convo = db.get_conversation(conversation_id, user["email"])
    if not convo:
        raise HTTPException(status_code=404, detail="conversation not found")
    return {"conversation": convo, "messages": db.get_messages(conversation_id)}


class ReplyPayload(BaseModel):
    body_html: str
    body_text: str | None = None


@router.post("/{conversation_id}/reply")
async def reply_to_thread(
    conversation_id: int,
    payload: ReplyPayload,
    user: dict = Depends(authenticate_session),
):
    """Reply to the venue within an existing thread. Continuing a conversation is
    not a new devis, so it is not counted against the send cap."""
    convo = db.get_conversation(conversation_id, user["email"])
    if not convo:
        raise HTTPException(status_code=404, detail="conversation not found")

    reply_to = build_reply_to(convo["reply_token"])
    subject = f"Re: Demande de devis mariage — {convo['venue_name']}"

    # Preserve the dev-mode guardrail: never reach the real venue in dev.
    if provider.current_mode == "dev":
        recipient = settings.test_email or settings.gmail_user
        if not recipient:
            raise HTTPException(status_code=400, detail="TEST_EMAIL non configuré en mode DEV.")
        subject = f"[DEV-TEST pour : {convo['venue_email'] or 'aucun'}] {subject}"
    else:
        recipient = convo["venue_email"]
        if not recipient:
            raise HTTPException(status_code=400, detail="L'adresse email du lieu est manquante.")

    result = await send_email(
        to=recipient, subject=subject, html_body=payload.body_html, reply_to=reply_to
    )
    if not result.success:
        raise HTTPException(status_code=502, detail=result.error)

    db.add_message(
        conversation_id,
        "out",
        from_addr=settings.from_email,
        to_addr=recipient,
        subject=subject,
        body_text=payload.body_text,
        body_html=payload.body_html,
    )
    return {"success": True, "sent_to": recipient, "mode": result.mode}


class SimulatePayload(BaseModel):
    reply_token: str
    from_addr: str = "venue@example.test"
    subject: str = "Re: votre demande de devis"
    body_text: str = "Bonjour, merci pour votre demande. Nous sommes disponibles à cette date."


@router.post("/_simulate")
def simulate_inbound(payload: SimulatePayload):
    """Dev-only: inject a fake venue reply so the inbox/thread UI can be built and
    tested without live DNS or a real Brevo inbound route."""
    if provider.current_mode != "dev":
        raise HTTPException(status_code=403, detail="simulation is dev-mode only")
    matched = _store_inbound(
        payload.reply_token,
        from_addr=payload.from_addr,
        to_addr=build_reply_to(payload.reply_token),
        subject=payload.subject,
        body_text=payload.body_text,
        body_html=None,
        raw_ref="simulated",
    )
    if not matched:
        raise HTTPException(status_code=404, detail="no conversation for that reply_token")
    return {"matched": True}
