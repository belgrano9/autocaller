from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from jinja2 import Environment, FileSystemLoader

from app import db
from app.config import settings
from app.routers.auth import authenticate_session, is_supervisor
from app.services import plans
from app.services.email_provider import build_reply_to, new_reply_token, send_email

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
async def send_outreach_email(
    payload: OutreachPayload,
    user: dict = Depends(authenticate_session),
):
    import app.services.email_provider as provider
    mode = provider.current_mode

    # --- Tier send-cap enforcement (supervisor bypasses) ---
    email = user["email"]
    plan = plans.effective_plan(user)
    quota = plans.quota_status(email, plan)
    if not is_supervisor(email) and quota["remaining"] is not None and quota["remaining"] <= 0:
        if payload.lang == "en":
            cap_msg = (
                "You've reached your free quota of 3 quote requests. Upgrade to send more."
                if plan == "free"
                else "You've reached your monthly quota of 15 quote requests. Upgrade for unlimited sends."
            )
        else:
            cap_msg = (
                "Vous avez atteint votre quota gratuit de 3 demandes de devis. Passez à un forfait supérieur pour en envoyer plus."
                if plan == "free"
                else "Vous avez atteint votre quota mensuel de 15 demandes de devis. Passez à la Conciergerie pour des envois illimités."
            )
        raise HTTPException(
            status_code=402,
            detail={"message": cap_msg, "reason": "quota_exceeded", "plan": plan},
        )

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

    # Opaque routing token for the venue's reply (devis+{token}@domain). It anchors
    # the conversation thread opened below, so the reply can be routed back here.
    reply_token = new_reply_token()
    reply_to = build_reply_to(reply_token)

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

    # Open the conciergerie thread (roadmap #4). venue_email is the real intended
    # target used to route replies; to_addr is where it actually went — in dev mode
    # that's TEST_EMAIL, preserving the "never contact venues in dev" guardrail.
    conversation_id = db.create_conversation(
        user_email=email,
        venue_name=payload.venue_name,
        venue_email=payload.venue_email,
        reply_token=reply_token,
    )
    db.add_message(
        conversation_id,
        "out",
        from_addr=settings.from_email,
        to_addr=recipient,
        subject=subject,
        body_html=html_content,
    )
    db.record_quote_send(email, payload.venue_name, conversation_id=conversation_id)
    quota_after = plans.quota_status(email, plan)
    return {
        "success": True,
        "mode": result.mode,
        "sent_to": recipient,
        "conversation_id": conversation_id,
        "quota": quota_after,
    }
