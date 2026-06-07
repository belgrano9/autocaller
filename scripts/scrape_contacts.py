#!/usr/bin/env python3
"""
Scrapes contact information and contact forms from wedding venue websites.
Uses Playwright to navigate, takes a screenshot of the contact page, sanitizes the DOM,
and analyzes the page using the Gemini API via the google-genai SDK.

Usage:
  uv run python scripts/scrape_contacts.py [options]

Options:
  --force       Process all venues, even if they already have email and phone.
  --limit N     Limit the execution to processing N venues.
  --venue NAME  Process only a specific venue by name (case-insensitive).
"""

import os
import re
import csv
import sys
import argparse
import unicodedata
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from dotenv import load_dotenv
from google import genai
from google.genai import types
from PIL import Image
from playwright.sync_api import sync_playwright

# Load environment variables
load_dotenv()
load_dotenv(dotenv_path="backend/.env")

# Paths adjusted to look at the parent directory (root of the workspace)
CSV_PATH = Path(__file__).parent.parent / "venues.csv"
SCREENSHOTS_DIR = Path(__file__).parent.parent / "screenshots"
FORMS_DIR = Path(__file__).parent.parent / "db" / "forms"

# Ensure directories exist
SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)
FORMS_DIR.mkdir(parents=True, exist_ok=True)


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

class ContactPageAnalysis(BaseModel):
    email: Optional[str] = Field(description="Any contact/booking email address found on the page, or null if none.")
    phone: Optional[str] = Field(description="Any contact telephone number found on the page (preferably French format), or null.")
    has_form: bool = Field(description="Whether a contact/inquiry form exists on the page.")
    form_details: Optional[ContactFormDetails] = Field(description="Details of the contact form if one exists, else null.")


def slugify(value: str) -> str:
    """Converts a string to a clean filename-safe slug."""
    value = unicodedata.normalize('NFKD', value).encode('ascii', 'ignore').decode('ascii')
    value = re.sub(r'[^\w\s-]', '', value).strip().lower()
    value = re.sub(r'[-\s]+', '_', value)
    return value


def clean_html(html_content: str) -> str:
    """Removes scripts, styles, heads, and comments to minimize DOM token usage."""
    soup = BeautifulSoup(html_content, "html.parser")
    # Decompose unwanted elements
    for tag in soup(["script", "style", "svg", "iframe", "noscript", "head", "link", "meta"]):
        tag.decompose()
    # Remove comments
    import bs4
    for element in soup.find_all(string=lambda s: isinstance(s, bs4.Comment)):
        element.extract()
    return str(soup.prettify())


def find_contact_page(page, website_url: str):
    """
    Tries to find a contact page link on the homepage and navigates to it.
    If none is found, stays on the homepage.
    """
    # Normalize URL
    url = website_url.strip()
    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    print(f"  Navigating to homepage: {url}")
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=25000)
        page.wait_for_timeout(2000)
    except Exception as e:
        # Retry with http if https fails
        if url.startswith("https://"):
            try:
                url_http = url.replace("https://", "http://")
                print(f"  Https failed ({e}). Retrying with http: {url_http}")
                page.goto(url_http, wait_until="domcontentloaded", timeout=25000)
                page.wait_for_timeout(2000)
            except Exception as e2:
                print(f"  Failed to load site {url}: {e2}")
                return False
        else:
            print(f"  Failed to load site {url}: {e}")
            return False

    # Look for contact links
    anchors = page.query_selector_all("a")
    contact_patterns = [
        r"contact", r"contactez", r"écrire", r"ecrire", r"mail", r"formulaire", 
        r"renseignement", r"devis", r"info", r"access", r"adresse"
    ]
    
    found_link = None
    for a in anchors:
        try:
            text = (a.text_content() or "").strip().lower()
            href = (a.get_attribute("href") or "").strip()
            
            if not href or href.startswith("#") or href.startswith("javascript:") or href.startswith("mailto:") or href.startswith("tel:"):
                continue
                
            # Check text or href for contact terms
            if any(re.search(pat, text) for pat in contact_patterns) or any(re.search(pat, href.lower()) for pat in contact_patterns):
                found_link = a
                # Stop early if we find an exact high-confidence match
                if "contact" in text or "contactez-nous" in text or "envoyez un mail" in text:
                    break
        except Exception:
            continue

    if found_link:
        try:
            href = found_link.get_attribute("href")
            contact_url = urljoin(page.url, href)
            print(f"  Found contact page link: {contact_url}. Navigating...")
            page.goto(contact_url, wait_until="domcontentloaded", timeout=25000)
            page.wait_for_timeout(2000)
        except Exception as e:
            print(f"  Failed to navigate to contact link: {e}. Staying on homepage.")
            
    return True


def analyze_contact_page(html_content: str, screenshot_path: Path, client: genai.Client) -> ContactPageAnalysis | None:
    """Sends clean DOM and screenshot to Gemini API for structured contact extraction."""
    cleaned_dom = clean_html(html_content)
    
    # Check if screenshot exists and can be loaded
    if not screenshot_path.exists():
        print(f"  Screenshot not found at {screenshot_path}")
        return None

    try:
        img = Image.open(screenshot_path)
    except Exception as e:
        print(f"  Failed to open screenshot image: {e}")
        return None

    prompt = (
        "You are an expert web scraping and data extraction assistant.\n"
        "Your task is to analyze the provided screenshot of the contact page and the cleaned HTML DOM of the page.\n"
        "Please extract:\n"
        "1. Any email address explicitly listed on the page. If multiple, choose the primary one for bookings or general inquiries.\n"
        "2. Any phone number (preferably in French format like 06 xx xx xx xx or 01 xx xx xx xx).\n"
        "3. Details of any contact/inquiry form on the page, including its fields, placeholders, labels, and whether fields are required.\n"
    )

    import time
    max_retries = 3
    for attempt in range(max_retries):
        try:
            response = client.models.generate_content(
                model='gemini-2.5-flash',
                contents=[img, f"Cleaned HTML DOM:\n{cleaned_dom}\n\nPrompt:\n{prompt}"],
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=ContactPageAnalysis,
                    temperature=0.1
                )
            )
            # Parse output JSON into the Pydantic model
            # The new SDK response.text returns the raw JSON string
            import json
            data = json.loads(response.text)
            return ContactPageAnalysis(**data)
        except Exception as e:
            print(f"  Gemini API call failed (attempt {attempt + 1}/{max_retries}): {e}")
            if attempt < max_retries - 1:
                time.sleep(3 * (attempt + 1))
            else:
                return None


def main():
    parser = argparse.ArgumentParser(description="Scrape contact pages and forms using Playwright and Gemini.")
    parser.add_argument("--force", action="store_true", help="Process all venues even if email and phone already exist.")
    parser.add_argument("--limit", type=int, default=None, help="Limit the number of venues to process.")
    parser.add_argument("--venue", type=str, default=None, help="Process only a specific venue by name.")
    args = parser.parse_args()

    # Verify Gemini API Key
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("Error: GEMINI_API_KEY environment variable is not set in environment or .env file.")
        print("Please set GEMINI_API_KEY in your .env or export it in your shell.")
        sys.exit(1)

    # Initialize Gemini Client
    client = genai.Client(api_key=api_key)

    # Read CSV
    if not CSV_PATH.exists():
        print(f"Error: CSV file not found at {CSV_PATH}")
        sys.exit(1)

    with open(CSV_PATH, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        fieldnames = list(reader.fieldnames)
        rows = list(reader)

    # Support last_verified column
    if "last_verified" not in fieldnames:
        fieldnames.append("last_verified")

    # Filter venues to process
    to_process = []
    for row in rows:
        name = row["name"]
        
        # Specific venue filter
        if args.venue and args.venue.lower() not in name.lower():
            continue
            
        # Already has details check
        has_details = bool(row.get("email")) and bool(row.get("phone"))
        if has_details and not args.force and not args.venue:
            # Skip if we already have both email and phone
            continue
            
        to_process.append(row)

    if args.limit:
        to_process = to_process[:args.limit]

    print(f"Found {len(to_process)} venues to process.")
    if not to_process:
        print("Nothing to process. Use --force to re-process all venues.")
        sys.exit(0)

    # Launch Playwright
    with sync_playwright() as p:
        print("Starting browser...")
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 800}
        )
        page = context.new_page()
        page.set_default_timeout(25000)

        for i, row in enumerate(to_process, 1):
            name = row["name"]
            website = row["website"]
            slug = slugify(name)
            
            print(f"\n[{i}/{len(to_process)}] Processing: {name} ({website})")
            
            if not website:
                print("  Skipping: No website URL specified.")
                continue

            success = find_contact_page(page, website)
            if not success:
                print("  Skipping: Could not load website.")
                continue

            # Capture screenshot
            screenshot_path = SCREENSHOTS_DIR / f"{slug}.png"
            try:
                # Capture the current viewport
                page.screenshot(path=str(screenshot_path), full_page=False)
                print(f"  Saved screenshot to: {screenshot_path}")
            except Exception as e:
                print(f"  Failed to take screenshot: {e}")
                continue

            # Get DOM HTML content
            html_content = page.content()

            # Analyze page with Gemini
            print("  Analyzing contact page with Gemini API...")
            analysis = analyze_contact_page(html_content, screenshot_path, client)

            if analysis:
                print(f"  Results:")
                print(f"    Email: {analysis.email}")
                print(f"    Phone: {analysis.phone}")
                print(f"    Form: {'Yes' if analysis.has_form else 'No'}")
                
                # Update CSV row
                if analysis.email:
                    # If the email is new or changed, set verification status to unchecked
                    if row.get("email") != analysis.email:
                        row["email"] = analysis.email
                        row["email_verified"] = "unchecked"
                if analysis.phone:
                    row["phone"] = analysis.phone
                row["last_verified"] = datetime.now().isoformat()

                # If email and phone were updated or already exist, we might adjust contact_type
                # E.g. if we have both email and phone: "email+phone", if only email: "email", etc.
                if row.get("email") and row.get("phone"):
                    row["contact_type"] = "email+phone"
                elif row.get("email"):
                    row["contact_type"] = "email"
                elif row.get("phone"):
                    row["contact_type"] = "phone"
                elif analysis.has_form:
                    row["contact_type"] = "form"

                # If has form, write JSON schema
                if analysis.has_form and analysis.form_details:
                    form_file = FORMS_DIR / f"{slug}.json"
                    # Add metadata
                    form_data = {
                        "venue_name": name,
                        "website": website,
                        "contact_url": page.url,
                        "extracted_email": analysis.email,
                        "extracted_phone": analysis.phone,
                        "form_details": analysis.form_details.model_dump(),
                        "last_verified": row["last_verified"]
                    }
                    import json
                    with open(form_file, "w", encoding="utf-8") as jf:
                        json.dump(form_data, jf, indent=2, ensure_ascii=False)
                    print(f"    Saved form details to: {form_file}")
            else:
                print("  Failed to get contact analysis from Gemini API.")

            # Save CSV progressively after each success/attempt to preserve progress
            with open(CSV_PATH, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(rows)
            print("  CSV updated.")

        browser.close()

    print("\nProcessing complete!")

if __name__ == "__main__":
    main()
