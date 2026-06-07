from fastapi import APIRouter, HTTPException

from app.services.email_provider import send_email

router = APIRouter(prefix="/test", tags=["test"])


@router.post("/send-email")
async def test_send_email(venue_name: str = "lieu test"):
    result = await send_email(
        to="xavipasobolivar@gmail.com",
        subject=f"Test contact — {venue_name}",
        html_body=f"<p>Bouton pressé pour <strong>{venue_name}</strong>.</p><p>Test Devis Mariages.</p>",
        reply_to="devis+test@devismariages.fr",
    )
    if not result.success:
        raise HTTPException(status_code=502, detail=result.error)
    return {"success": True, "mode": result.mode}
