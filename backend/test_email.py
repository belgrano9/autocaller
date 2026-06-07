"""
Smoke test: send one email via Mailgun.
Run from backend/: uv run python test_email.py
"""
import asyncio
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

from app.services.email_provider import send_email  # noqa: E402


async def main() -> None:
    result = await send_email(
        to="xavipasobolivar@gmail.com",
        subject="Test Devis Mariages",
        html_body="<p>Ceci est un test. Si vous recevez cet email, Mailgun fonctionne correctement.</p>",
        reply_to="devis+test@devismariages.fr",
    )
    if result.success:
        print(f"OK — message_id: {result.message_id}")
    else:
        print(f"FAILED — {result.error}", file=sys.stderr)
        sys.exit(1)


asyncio.run(main())
