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
    lang: str = "fr"


def render_outreach_html(payload: OutreachPayload) -> str:
    try:
        template_name = "outreach_en.html" if payload.lang == "en" else "outreach.html"
        template = jinja_env.get_template(template_name)
        return template.render(
            couple_name=payload.couple_name,
            venue_name=payload.venue_name,
            event_date=payload.event_date,
            guest_count=payload.guest_count,
            style="",  # Left blank/optional
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

    if payload.lang == "en":
        subject = f"Wedding quote request — {payload.couple_name}"
        dev_label = "none" if not payload.venue_email else payload.venue_email
        dev_prefix = f"[DEV-TEST to: {dev_label}]"
        none_label = "Manual (No email)"
    else:
        subject = f"Demande de devis mariage — {payload.couple_name}"
        dev_label = "aucun" if not payload.venue_email else payload.venue_email
        dev_prefix = f"[DEV-TEST pour : {dev_label}]"
        none_label = "Manuel (Aucun email)"

    if mode == "dev":
        recipient = settings.test_email or settings.gmail_user
        subject_preview = f"{dev_prefix} {subject}"
    else:
        recipient = payload.venue_email
        subject_preview = subject

    return {
        "html": html_content,
        "from": f"{settings.from_name} <{settings.from_email}>",
        "to": recipient or none_label,
        "subject": subject_preview,
        "mode": mode,
    }


@router.post("/send")
async def send_outreach_email(payload: OutreachPayload):
    import app.services.email_provider as provider
    mode = provider.current_mode

    if not payload.venue_email and mode == "int":
        err_msg = (
            "Wedding venue email address is missing."
            if payload.lang == "en"
            else "L'adresse email du lieu est manquante."
        )
        raise HTTPException(status_code=400, detail=err_msg)

    html_content = render_outreach_html(payload)
    
    if payload.lang == "en":
        subject = f"Wedding quote request — {payload.couple_name}"
        dev_label = "none" if not payload.venue_email else payload.venue_email
        dev_prefix = f"[DEV-TEST to: {dev_label}]"
        dev_err = "TEST_EMAIL not configured in DEV mode."
    else:
        subject = f"Demande de devis mariage — {payload.couple_name}"
        dev_label = "aucun" if not payload.venue_email else payload.venue_email
        dev_prefix = f"[DEV-TEST pour : {dev_label}]"
        dev_err = "TEST_EMAIL non configuré en mode DEV."

    # Generate a simple reply_to alias based on the couple name
    # e.g., devis+alicebob@domain.com
    couple_clean = re.sub(r"[^a-zA-Z0-9]", "", payload.couple_name.lower())[:15]
    reply_to = f"devis+{couple_clean}@{settings.reply_to_domain}"

    if mode == "dev":
        recipient = settings.test_email or settings.gmail_user
        if not recipient:
            raise HTTPException(status_code=400, detail=dev_err)
        subject = f"{dev_prefix} {subject}"
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
