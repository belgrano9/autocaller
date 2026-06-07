"""
Email verification for venues.csv.
For each row with an email:
  1. Check MX record exists (DNS)
  2. For non-Gmail/Yahoo domains: attempt SMTP RCPT TO without sending

Updates email_verified column with:
  no_email     — no email address in row
  invalid      — malformed address
  no_mx        — domain has no MX record (dead)
  mx_ok        — MX found; SMTP skipped (Gmail/Yahoo/hosted)
  smtp_ok      — MX found + SMTP confirmed mailbox exists
  smtp_unknown — MX found but server blocked verification

Run: uv run python scripts/verify_emails.py
"""

import csv
import re
import smtplib
import socket
import time
from pathlib import Path

import dns.resolver

# Adjusted to look in the parent directory (root of the workspace)
CSV_PATH = Path(__file__).parent.parent / "venues.csv"

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
HOSTED_PROVIDERS = {
    "gmail.com", "googlemail.com",
    "yahoo.fr", "yahoo.com",
    "hotmail.com", "hotmail.fr",
    "outlook.com", "outlook.fr",
    "orange.fr", "free.fr",
    "laposte.net", "sfr.fr",
    "eatbu.com",  # restaurant platform — ignore
}
TIMEOUT = 6


def get_mx(domain: str) -> str | None:
    try:
        records = dns.resolver.resolve(domain, "MX", lifetime=TIMEOUT)
        best = sorted(records, key=lambda r: r.preference)[0]
        return str(best.exchange).rstrip(".")
    except Exception:
        return None


def smtp_verify(mx_host: str, email: str) -> str:
    try:
        with smtplib.SMTP(timeout=TIMEOUT) as s:
            s.connect(mx_host, 25)
            s.ehlo("verify.devismariages.fr")
            s.mail("verify@devismariages.fr")
            code, _ = s.rcpt(email)
            if code == 250:
                return "smtp_ok"
            return "smtp_unknown"
    except smtplib.SMTPRecipientsRefused:
        return "smtp_unknown"
    except Exception:
        return "smtp_unknown"


def verify(email: str) -> str:
    if not email:
        return "no_email"
    if not EMAIL_RE.match(email):
        return "invalid"

    domain = email.split("@")[1].lower()
    mx = get_mx(domain)
    if not mx:
        return "no_mx"

    if domain in HOSTED_PROVIDERS:
        return "mx_ok"

    result = smtp_verify(mx, email)
    time.sleep(0.3)
    return result


def main():
    with open(CSV_PATH, encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    total = len(rows)
    with_email = sum(1 for r in rows if r["email"])

    print(f"{total} venues, {with_email} with email addresses\n")

    for i, row in enumerate(rows, 1):
        if row["email_verified"] not in ("unchecked", ""):
            print(f"  [{i}/{total}] {row['name']} — already {row['email_verified']}, skipping")
            continue

        status = verify(row["email"])
        row["email_verified"] = status

        icon = {"no_email": "-", "no_mx": "X", "mx_ok": "~", "smtp_ok": "OK", "smtp_unknown": "?", "invalid": "X"}.get(status, "?")
        print(f"  [{i}/{total}] {icon} {row['name']:40s} {row['email'] or '(no email)':45s} -> {status}")

    fieldnames = list(rows[0].keys())
    with open(CSV_PATH, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    verified = sum(1 for r in rows if r["email_verified"] == "smtp_ok")
    mx_ok = sum(1 for r in rows if r["email_verified"] == "mx_ok")
    no_mx = sum(1 for r in rows if r["email_verified"] == "no_mx")
    no_email = sum(1 for r in rows if r["email_verified"] == "no_email")

    print(f"\nDone. smtp_ok={verified}  mx_ok={mx_ok}  no_mx={no_mx}  no_email={no_email}")
    print(f"Results saved to {CSV_PATH}")


if __name__ == "__main__":
    main()
