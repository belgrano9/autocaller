#!/usr/bin/env python3
"""
Visual QA Verifier & Corrector for scraped contact forms.
Loads locally captured screenshots and cross-references them with draft JSON schemas
extracted from the HTML DOM to verify visual accuracy, correct any mismatches,
and confirm the form is visible and submit-ready.

Usage:
  uv run python scripts/analyze_screenshots.py [options]

Options:
  --force            Process all screenshots, even if already marked last_verified.
  --venue NAME       Process only a specific venue by name.
  --screenshot PATH  Process only a specific screenshot file path.
"""

import os
import re
import csv
import sys
import json
import argparse
import unicodedata
import time
from datetime import datetime
from pathlib import Path

# Force stdout/stderr to UTF-8 to prevent encoding crashes on Windows console
try:
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
except Exception:
    pass

from dotenv import load_dotenv
from google import genai
from google.genai import types
from loguru import logger
from PIL import Image
from rich.console import Console
from rich.panel import Panel
from rich.progress import BarColumn, Progress, SpinnerColumn, TaskProgressColumn, TextColumn
from rich.table import Table

console = Console()

# Configure loguru: Log only to file, disable stdout output
logger.remove()
logger.add("logs/analyzer.log", rotation="10 MB", level="DEBUG", encoding="utf-8")

# Paths
CSV_PATH = Path(__file__).parent.parent / "venues.csv"
SCREENSHOTS_DIR = Path(__file__).parent.parent / "screenshots"
FORMS_DIR = Path(__file__).parent.parent / "db" / "forms"


# --- Structured Output Schemas ---
from pydantic import BaseModel, Field
from typing import List, Optional

class ContactFormField(BaseModel):
    name: Optional[str] = Field(description="The 'name' attribute of the input/textarea field, or a descriptive placeholder if missing.")
    type: Optional[str] = Field(description="The type of the field (e.g., text, email, tel, textarea, select, checkbox, radio).")
    label: Optional[str] = Field(description="The label or visual text associated with this field.")
    required: bool = Field(description="Whether the field is marked as required.")
    placeholder: Optional[str] = Field(description="The placeholder text of the field, if any.")

class ContactFormDetails(BaseModel):
    action: Optional[str] = Field(description="The action URL/endpoint of the form, if any.")
    method: Optional[str] = Field(description="The HTTP method of the form (e.g., POST, GET).")
    fields: List[ContactFormField] = Field(description="List of fields present in the contact form.")

class VisualFormVerification(BaseModel):
    form_is_visible: bool = Field(description="True if the contact form is visible in the screenshot.")
    submit_button_is_visible: bool = Field(description="True if the submit/send/confirm button for the form is visible in the screenshot.")
    is_draft_accurate: bool = Field(description="True if the draft JSON matches the screenshot perfectly without corrections.")
    extracted_email: Optional[str] = Field(description="Any email address visible on the page (e.g. in text, header, footer) that can be used for contact. Null if none is visible.")
    extracted_phone: Optional[str] = Field(description="Any phone number visible on the page (preferably French format) that can be used for contact. Null if none is visible.")
    verified_form_details: Optional[ContactFormDetails] = Field(description="The corrected/verified form schema matching the screenshot. Null if no form is visible.")
    verification_notes: Optional[str] = Field(description="Explanation of any corrections made or reasons for verification failure.")


def slugify(value: str) -> str:
    """Converts a string to a clean filename-safe slug."""
    value = unicodedata.normalize('NFKD', value).encode('ascii', 'ignore').decode('ascii')
    value = re.sub(r'[^\w\s-]', '', value).strip().lower()
    value = re.sub(r'[-\s]+', '_', value)
    return value


def format_french_phone(phone: str) -> str:
    """Standardizes French phone numbers to the local format '0X XX XX XX XX' or returns clean digits/input if not French."""
    if not phone or phone.strip() in ("", "-", "None"):
        return ""
    
    parts = re.split(r'[/,]', phone)
    formatted_parts = []
    
    for part in parts:
        part = part.strip()
        if not part:
            continue
            
        digits = "".join(c for c in part if c.isdigit())
        
        if digits.startswith("0033"):
            digits = "33" + digits[4:]
            
        if digits.startswith("33"):
            if len(digits) > 2 and digits[2] == "0":
                digits = "33" + digits[3:]
            digits = "0" + digits[2:]
            
        if len(digits) == 9 and not digits.startswith("0"):
            digits = "0" + digits
            
        if len(digits) == 10 and digits.startswith("0"):
            formatted = f"{digits[0:2]} {digits[2:4]} {digits[4:6]} {digits[6:8]} {digits[8:10]}"
            formatted_parts.append(formatted)
        else:
            formatted_parts.append(part)
            
    return " / ".join(formatted_parts)


def verify_screenshot_with_gemini(screenshot_path: Path, draft_schema: Optional[dict], client: genai.Client) -> VisualFormVerification | None:
    """Calls Gemini to visually verify the screenshot against the draft JSON schema."""
    if not screenshot_path.exists():
        logger.warning(f"Screenshot not found at {screenshot_path}")
        return None

    try:
        img = Image.open(screenshot_path)
    except Exception as e:
        logger.warning(f"Failed to open screenshot image: {e}")
        return None

    draft_json_str = json.dumps(draft_schema, indent=2, ensure_ascii=False) if draft_schema else "None provided."

    prompt = (
        "You are an expert visual Quality Assurance (QA) assistant for contact form web scrapers.\n"
        "Your task is to analyze the screenshot of a contact page and cross-reference it with a draft form schema extracted from the HTML DOM.\n\n"
        f"Draft Form Schema:\n{draft_json_str}\n\n"
        "Instructions:\n"
        "1. Check if a contact/inquiry form is visible in the screenshot.\n"
        "2. Check if the submit/send/confirm button for that form is visible in the screenshot.\n"
        "3. Look for any email addresses or phone numbers visible anywhere on the page (headers, footers, body text) and extract them.\n"
        "4. Compare the visible form fields in the screenshot with the provided draft schema. Correct any errors in the schema (e.g. incorrect field labels, missing fields, or wrong field types) to match exactly what is visually present.\n"
        "5. If no draft schema was provided, extract the form schema from scratch based on the screenshot.\n"
        "6. Output the result in the required JSON structure."
    )

    max_retries = 3
    for attempt in range(max_retries):
        try:
            logger.debug(f"Calling Gemini API (attempt {attempt + 1}/{max_retries})...")
            response = client.models.generate_content(
                model='gemini-2.5-flash',
                contents=[img, prompt],
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=VisualFormVerification,
                    temperature=0.1
                )
            )
            # Parse output JSON
            data = json.loads(response.text)
            return VisualFormVerification(**data)
        except Exception as e:
            logger.warning(f"Gemini API call failed (attempt {attempt + 1}/{max_retries}): {e}")
            if attempt < max_retries - 1:
                if "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e):
                    console.print("[yellow]⚠️  Gemini Rate Limit (429) hit. Pausing for 60 seconds to cool down...[/yellow]")
                    time.sleep(60)
                else:
                    time.sleep(3 * (attempt + 1))
            else:
                return None


def main():
    parser = argparse.ArgumentParser(description="Verify contact form screenshots against draft JSON schemas using Gemini.")
    parser.add_argument("--force", action="store_true", help="Re-verify screenshots even if already verified in CSV.")
    parser.add_argument("--venue", type=str, default=None, help="Verify only a specific venue by name.")
    parser.add_argument("--screenshot", type=str, default=None, help="Verify only a specific screenshot file path.")
    args = parser.parse_args()

    # Load environment variables
    load_dotenv()
    load_dotenv(dotenv_path="backend/.env")

    Path("logs").mkdir(parents=True, exist_ok=True)

    console.print(Panel.fit(
        "[bold cyan]Autocaller Visual QA Verifier[/bold cyan]\n"
        "[dim]Cross-referencing screenshots & DOM form schemas[/dim]",
        border_style="cyan"
    ))

    # Verify Gemini API Key
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        console.print("[bold red]Error: GEMINI_API_KEY environment variable is not set in environment or .env file.[/bold red]")
        logger.error("GEMINI_API_KEY not found.")
        sys.exit(1)

    # Initialize Gemini Client
    client = genai.Client(api_key=api_key)

    # Read CSV
    if not CSV_PATH.exists():
        console.print(f"[bold red]Error: CSV file not found at {CSV_PATH}[/bold red]")
        logger.error(f"CSV file not found at {CSV_PATH}")
        sys.exit(1)

    with open(CSV_PATH, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        fieldnames = list(reader.fieldnames)
        rows = list(reader)

    # Support last_verified column
    if "last_verified" not in fieldnames:
        fieldnames.append("last_verified")

    # Map slugified venue names to rows
    venue_map = {}
    for r in rows:
        slug = slugify(r["name"])
        venue_map[slug] = r

    # Determine screenshots to process
    screenshots_to_process = []
    
    if args.screenshot:
        spath = Path(args.screenshot)
        if not spath.exists():
            console.print(f"[bold red]Error: Screenshot file not found at {spath}[/bold red]")
            sys.exit(1)
        slug = spath.stem
        if slug in venue_map:
            screenshots_to_process.append((spath, slug, venue_map[slug]))
        else:
            console.print(f"[bold red]Error: Could not map screenshot '{spath.name}' to any venue in venues.csv.[/bold red]")
            sys.exit(1)
            
    elif args.venue:
        target_venue = args.venue.lower()
        matched = False
        for slug, r in venue_map.items():
            if target_venue in r["name"].lower():
                spath = SCREENSHOTS_DIR / f"{slug}.png"
                if spath.exists():
                    screenshots_to_process.append((spath, slug, r))
                    matched = True
                else:
                    console.print(f"[yellow]Warning: Screenshot for venue '{r['name']}' not found at {spath}[/yellow]")
        if not matched:
            console.print(f"[bold red]Error: No screenshot matches venue name '{args.venue}'[/bold red]")
            sys.exit(1)
            
    else:
        # Scan screenshots directory
        if not SCREENSHOTS_DIR.exists():
            console.print(f"[bold red]Error: Screenshots directory not found at {SCREENSHOTS_DIR}[/bold red]")
            sys.exit(1)
            
        for file in SCREENSHOTS_DIR.glob("*.png"):
            if file.stem == "README":
                continue
            slug = file.stem
            if slug in venue_map:
                row = venue_map[slug]
                # Skip if already verified (and not forcing)
                if row.get("last_verified") and not args.force:
                    continue
                screenshots_to_process.append((file, slug, row))
            else:
                logger.warning(f"Could not map screenshot '{file.name}' to a venue in venues.csv.")
                console.print(f"[yellow]⚠️  Skipping untracked screenshot: {file.name}[/yellow]")

    logger.info(f"Selected {len(screenshots_to_process)} screenshots for QA verification.")

    if not screenshots_to_process:
        console.print("[yellow]No screenshots require verification. Use --force to re-verify.[/yellow]")
        return

    processed_results = []

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        console=console
    ) as progress:
        task = progress.add_task("[cyan]Verifying screenshots...", total=len(screenshots_to_process))

        for original_idx, (spath, slug, row) in enumerate(screenshots_to_process, 1):
            name = row["name"]
            progress.update(task, description=f"[cyan]QA Checking: {name}")
            logger.info(f"QA Check [{original_idx}/{len(screenshots_to_process)}]: {name} ({spath.name})")

            # Load draft schema if it exists
            draft_file = FORMS_DIR / f"{slug}.json"
            draft_schema = None
            if draft_file.exists():
                try:
                    with open(draft_file, encoding="utf-8") as jf:
                        draft_schema = json.load(jf)
                    logger.debug(f"Loaded draft schema from {draft_file}")
                except Exception as e:
                    logger.warning(f"Failed to read draft schema {draft_file}: {e}")

            # Call Gemini visual verification
            verification = verify_screenshot_with_gemini(spath, draft_schema, client)

            if verification:
                # Is useful? Form and submit button must both be visible
                is_useful = verification.form_is_visible and verification.submit_button_is_visible
                logger.info(f"QA Result for {name}: form_visible={verification.form_is_visible}, btn_visible={verification.submit_button_is_visible}, accurate={verification.is_draft_accurate}")
                
                # Update CSV row verification metadata
                row["last_verified"] = datetime.now().isoformat()

                if is_useful and verification.verified_form_details:
                    # Update email and phone in CSV row if Gemini found/corrected them
                    new_email = verification.extracted_email or (draft_schema.get("extracted_email") if draft_schema else None) or row.get("email")
                    new_phone = format_french_phone(verification.extracted_phone or (draft_schema.get("extracted_phone") if draft_schema else None) or row.get("phone"))
                    if new_email:
                        row["email"] = new_email
                    if new_phone:
                        row["phone"] = new_phone

                    # Update contact type in CSV to form (or email+form if email exists)
                    if row.get("email"):
                        row["contact_type"] = "email+form"
                    else:
                        row["contact_type"] = "form"

                    # Save verified JSON schema
                    verified_data = {
                        "venue_name": name,
                        "website": row.get("website"),
                        "contact_url": draft_schema.get("contact_url") if draft_schema else None,
                        "extracted_email": row.get("email"),
                        "extracted_phone": row.get("phone"),
                        "form_details": verification.verified_form_details.model_dump(),
                        "last_verified": row["last_verified"],
                        "qa_verified": True,
                        "qa_accurate": verification.is_draft_accurate,
                        "qa_notes": verification.verification_notes
                    }
                    
                    with open(draft_file, "w", encoding="utf-8") as jf:
                        json.dump(verified_data, jf, indent=2, ensure_ascii=False)
                    logger.info(f"Saved verified form to: {draft_file}")

                    status_msg = "[green]Verified ✓[/green]"
                    if not verification.is_draft_accurate:
                        status_msg = "[yellow]Corrected & Verified ✓[/yellow]"
                    progress.console.print(f"[{'green' if verification.is_draft_accurate else 'yellow'}]✅ [{original_idx}] {name:30s} -> {status_msg}[/{'green' if verification.is_draft_accurate else 'yellow'}]")
                    processed_results.append((name, spath.name, "Verified" if verification.is_draft_accurate else "Corrected", verification.verification_notes))
                else:
                    # Not useful: remove JSON file if it exists, mark as manual
                    if draft_file.exists():
                        try:
                            draft_file.unlink()
                            logger.info(f"Removed unverified/non-useful form schema file: {draft_file}")
                        except Exception as e:
                            logger.error(f"Failed to delete {draft_file}: {e}")
                    
                    row["contact_type"] = "manual"
                    progress.console.print(f"[red]❌ [{original_idx}] {name:30s} -> Failed QA (Form/button not visible)[/red]")
                    processed_results.append((name, spath.name, "Failed QA", verification.verification_notes or "Form/button not visible"))
            else:
                progress.console.print(f"[yellow]⚠️  [{original_idx}] {name:30s} -> Analysis failed (API error)[/yellow]")
                processed_results.append((name, spath.name, "API Error", "Gemini failed to respond"))

            # Update CSV progressively
            with open(CSV_PATH, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(rows)
            logger.debug("Progressively updated CSV.")
            progress.advance(task)

    # Summary Table
    table = Table(title="Visual QA Results", show_header=True, header_style="bold cyan")
    table.add_column("Venue", style="dim")
    table.add_column("Screenshot", style="dim")
    table.add_column("QA Result", style="bold")
    table.add_column("Notes", style="italic")

    for name, shot, result, notes in processed_results:
        color = "green" if result == "Verified" else ("yellow" if result == "Corrected" else "red")
        table.add_row(name, shot, f"[{color}]{result}[/{color}]", notes or "-")

    console.print("\n")
    console.print(table)


if __name__ == "__main__":
    main()
