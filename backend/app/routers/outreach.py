import re
from pathlib import Path
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from jinja2 import Environment, FileSystemLoader

from app.config import settings
from app.services.email_provider import send_email

router = APIRouter(prefix="/outreach", tags=["outreach"])

# Jinja2 template setup
TEMPLATES_DIR = Path(__file__).parent.parent / "templates"
jinja_env = Environment(loader=FileSystemLoader(TEMPLATES_DIR))


class OutreachPayload(BaseModel):
    couple_name: str
    event_date: str
    guest_count: str
    budget: str
    notes: str | None = None
    venue_name: str
    venue_email: str | None = None


def render_outreach_html(payload: OutreachPayload) -> str:
    try:
        template = jinja_env.get_template("outreach.html")
        return template.render(
            couple_name=payload.couple_name,
            venue_name=payload.venue_name,
            event_date=payload.event_date,
            guest_count=payload.guest_count,
            style="",  # Left blank/optional in outreach.html
            budget=payload.budget,
            notes=payload.notes,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to render template: {str(e)}")


@router.post("/preview")
def preview_email(payload: OutreachPayload):
    html_content = render_outreach_html(payload)

    import app.services.email_provider as provider
    mode = provider.current_mode

    subject = f"Demande de devis mariage — {payload.couple_name}"

    if mode == "dev":
        recipient = settings.test_email or settings.gmail_user
        subject_preview = f"[DEV-TEST pour : {payload.venue_email or 'aucun'}] {subject}"
    else:
        recipient = payload.venue_email
        subject_preview = subject

    return {
        "html": html_content,
        "from": f"{settings.from_name} <{settings.from_email}>",
        "to": recipient or "Manuel (Aucun email)",
        "subject": subject_preview,
        "mode": mode,
    }


@router.post("/send")
async def send_outreach_email(payload: OutreachPayload):
    import app.services.email_provider as provider
    mode = provider.current_mode

    if not payload.venue_email and mode == "int":
        raise HTTPException(status_code=400, detail="L'adresse email du lieu est manquante.")

    html_content = render_outreach_html(payload)
    subject = f"Demande de devis mariage — {payload.couple_name}"

    # Generate a simple reply_to alias based on the couple name
    # e.g., devis+alicebob@domain.com
    couple_clean = re.sub(r"[^a-zA-Z0-9]", "", payload.couple_name.lower())[:15]
    reply_to = f"devis+{couple_clean}@{settings.reply_to_domain}"

    if mode == "dev":
        recipient = settings.test_email or settings.gmail_user
        if not recipient:
            raise HTTPException(status_code=400, detail="TEST_EMAIL non configuré en mode DEV.")
        subject = f"[DEV-TEST pour : {payload.venue_email or 'aucun'}] {subject}"
    else:
        recipient = payload.venue_email

    result = await send_email(
        to=recipient,
        subject=subject,
        html_body=html_content,
        reply_to=reply_to,
    )

    if not result.success:
        raise HTTPException(status_code=502, detail=result.error)

    return {"success": True, "mode": result.mode, "sent_to": recipient}
