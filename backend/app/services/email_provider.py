"""
Dual-mode email provider.
  dev  → Gmail SMTP (personal account)
  int  → Brevo SMTP (smtp-relay.brevo.com)
"""

import asyncio
import hashlib
import hmac
import secrets
import smtplib
import time
from dataclasses import dataclass
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from loguru import logger

from app.config import settings

# Runtime-mutable mode — starts from .env, togglable via /api/mode
current_mode: str = settings.app_mode


@dataclass
class SendResult:
    success: bool
    mode: str
    error: str | None = None


def _smtp_config() -> tuple[str, int, str, str]:
    """Returns (host, port, user, password) for the current mode."""
    if current_mode == "int":
        return "smtp-relay.brevo.com", 587, settings.brevo_smtp_user, settings.brevo_smtp_password
    return "smtp.gmail.com", 587, settings.gmail_user, settings.gmail_app_password


def _send_sync(to: str, subject: str, html_body: str, reply_to: str) -> None:
    host, port, user, password = _smtp_config()
    msg = MIMEMultipart("alternative")
    msg["From"] = f"{settings.from_name} <{settings.from_email}>"
    msg["To"] = to
    msg["Subject"] = subject
    msg["Reply-To"] = reply_to
    msg.attach(MIMEText(html_body, "html"))
    with smtplib.SMTP(host, port) as s:
        s.starttls()
        s.login(user, password)
        s.sendmail(settings.from_email, [to], msg.as_string())


async def send_email(to: str, subject: str, html_body: str, reply_to: str) -> SendResult:
    host, _, user, _ = _smtp_config()
    logger.info("Sending via {} ({}) → {}", current_mode, host, to)
    try:
        await asyncio.to_thread(_send_sync, to, subject, html_body, reply_to)
        logger.success("Sent OK ({} → {})", current_mode, to)
        return SendResult(success=True, mode=current_mode)
    except Exception as exc:
        logger.error("Send failed ({} → {}): {}", current_mode, to, exc)
        return SendResult(success=False, mode=current_mode, error=str(exc))


def new_reply_token() -> str:
    """Mints an opaque, unguessable routing token for a conversation's Reply-To.
    Replaces the old couple-name-derived alias (collided across couples, leaked
    which couple, and was trivially spoofable on inbound)."""
    return secrets.token_urlsafe(9)


def build_reply_to(token: str) -> str:
    return f"devis+{token}@{settings.reply_to_domain}"


def verify_webhook_signature(timestamp: str, token: str, signature: str) -> bool:
    if abs(time.time() - int(timestamp)) > 300:
        return False
    value = timestamp + token
    digest = hmac.new(
        settings.webhook_signing_key.encode(),
        value.encode(),
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(digest, signature)
