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
import sys
import time
from pathlib import Path

# Reconfigure stdout/stderr to UTF-8 to prevent encoding crashes on Windows console
try:
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
except Exception:
    pass

import dns.resolver
from loguru import logger
from rich.console import Console
from rich.panel import Panel
from rich.progress import BarColumn, Progress, SpinnerColumn, TaskProgressColumn, TextColumn
from rich.table import Table

console = Console()

# Configure loguru: Log only to file, disable stdout output
logger.remove()
logger.add("logs/verify_emails.log", rotation="10 MB", level="DEBUG", encoding="utf-8")

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
    Path("logs").mkdir(parents=True, exist_ok=True)
    
    console.print(Panel.fit(
        "[bold green]SMTP Email Verifier[/bold green]\n"
        "[dim]DNS & SMTP Mailbox Verification[/dim]", 
        border_style="green"
    ))
    
    logger.info("Starting email verification process.")

    if not CSV_PATH.exists():
        console.print(f"[bold red]Error: CSV file not found at {CSV_PATH}[/bold red]")
        logger.error(f"CSV file not found at {CSV_PATH}")
        sys.exit(1)

    with open(CSV_PATH, encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    total = len(rows)
    with_email = sum(1 for r in rows if r["email"])

    logger.debug(f"Loaded {total} venues from CSV. {with_email} have emails.")

    # Filter rows that need verification (email_verified is unchecked or empty)
    to_verify = []
    for i, row in enumerate(rows, 1):
        if row["email_verified"] in ("unchecked", "") and row["email"]:
            to_verify.append((i, row))

    if not to_verify:
        console.print("[yellow]No emails require verification (all status values are already set).[/yellow]")
        logger.info("No emails require verification.")
        return

    results = []

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        console=console
    ) as progress:
        task = progress.add_task("[cyan]Verifying emails...", total=len(to_verify))

        for original_index, row in to_verify:
            name = row["name"]
            email = row["email"]
            progress.update(task, description=f"[cyan]Verifying: {name} ({email})")
            logger.debug(f"Verifying [{original_index}] {name} ({email})")

            status = verify(email)
            row["email_verified"] = status
            logger.info(f"Venue '{name}' email '{email}' -> {status}")

            icon = {
                "no_email": "-", "no_mx": "❌", "mx_ok": "☁️", 
                "smtp_ok": "✅", "smtp_unknown": "❓", "invalid": "⚠️"
            }.get(status, "❓")
            
            color = {
                "no_email": "dim", "no_mx": "red", "mx_ok": "blue", 
                "smtp_ok": "green", "smtp_unknown": "yellow", "invalid": "red"
            }.get(status, "white")

            progress.console.print(f"[{color}]{icon} [{original_index}] {name:30s} -> {status}[/{color}]")
            results.append((name, email, status, icon, color))
            progress.advance(task)

    # Save CSV
    fieldnames = list(rows[0].keys())
    with open(CSV_PATH, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    logger.info("CSV file saved successfully.")

    # Summary Table
    table = Table(title="Verification Summary", show_header=True, header_style="bold green")
    table.add_column("Venue", style="dim")
    table.add_column("Email", style="cyan")
    table.add_column("Status", style="bold")
    table.add_column("Details", style="dim")

    for name, email, status, icon, color in results:
        status_text = f"[{color}]{icon} {status}[/{color}]"
        details_text = {
            "smtp_ok": "Mailbox exists & verified",
            "mx_ok": "Domain valid (Gmail/Yahoo skipped)",
            "no_mx": "No MX records found (domain dead)",
            "smtp_unknown": "MX valid, SMTP refused test handshake",
            "invalid": "Malformed email address",
            "no_email": "No email address"
        }.get(status, status)
        table.add_row(name, email, status_text, details_text)

    console.print("\n")
    console.print(table)

    verified = sum(1 for r in rows if r["email_verified"] == "smtp_ok")
    mx_ok = sum(1 for r in rows if r["email_verified"] == "mx_ok")
    no_mx = sum(1 for r in rows if r["email_verified"] == "no_mx")
    no_email = sum(1 for r in rows if r["email_verified"] == "no_email")

    console.print(Panel(
        f"[bold]Total summary across CSV:[/bold]\n"
        f"✅ smtp_ok: [green]{verified}[/green]   "
        f"☁️ mx_ok: [blue]{mx_ok}[/blue]   "
        f"❌ no_mx: [red]{no_mx}[/red]   "
        f"➖ no_email: [dim]{no_email}[/dim]",
        title="Final Stats",
        border_style="green"
    ))


if __name__ == "__main__":
    main()
