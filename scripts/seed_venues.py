#!/usr/bin/env python3
"""
Seeds new wedding venues into 'venues.csv' for a given French region.

This script expands venue coverage beyond the current dataset. For each region:
  1. It asks Gemini (with Google Search grounding) for real, operating wedding
     venues in the region: name, city, department code, type, official website.
  2. A second non-grounded Gemini call structures the research notes into JSON
     (the google_search tool cannot be combined with structured output on
     gemini-2.5-flash, hence the two-step pattern).
  3. Each candidate passes a gate before entering the CSV:
       a. Dedup against existing rows (slugified name + website domain).
       b. Sanity checks (department belongs to the region, allowed type,
          no directory/social-media URLs).
       c. Playwright validation: the website loads and its content plausibly
          matches the venue (name tokens or wedding-related terms).
  4. Accepted rows are appended to 'venues.csv' progressively, with enrichment
     columns left empty (email_verified="unchecked") so the existing pipeline
     (scrape_contacts.py -> verify_emails.py -> scrape_photos.py) fills them.

Execution:
  uv run python scripts/seed_venues.py [options]

Options:
  --region NAME    Region to seed (must be a known metropolitan region).
  --all-defaults   Seed the default target regions sequentially.
  --target N       Number of venues to ADD per region after validation (default 25).
  --dry-run        Validate fully but print results without writing the CSV.
  --model NAME     Gemini model to use (default gemini-2.5-flash).
"""

import os
import csv
import sys
import json
import time
import argparse
import unicodedata
from pathlib import Path
from urllib.parse import urlparse

# Reconfigure stdout/stderr to UTF-8 to prevent encoding crashes on Windows console
try:
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
except Exception:
    pass

from dotenv import load_dotenv
from google import genai
from google.genai import types
from loguru import logger
from playwright.sync_api import sync_playwright
from rich.console import Console
from rich.panel import Panel
from rich.progress import BarColumn, Progress, SpinnerColumn, TaskProgressColumn, TextColumn
from rich.table import Table

from models import VenueCandidate
from utils import slugify

console = Console()

# Configure loguru: Log only to file, disable stdout output
logger.remove()
logger.add("logs/seeder.log", rotation="10 MB", level="DEBUG", encoding="utf-8")

CSV_PATH = Path(__file__).parent.parent / "venues.csv"

ALLOWED_TYPES = {"château", "domaine", "salle", "ferme", "manoir", "atypique"}

# Maps normalized (accent-stripped, lowercase) type strings to canonical CSV types
TYPE_ALIASES = {
    "chateau":             "château",
    "domaine":             "domaine",
    "salle":               "salle",
    "salle de reception":  "salle",
    "salle des fetes":     "salle",
    "espace de reception": "salle",
    "ferme":               "ferme",
    "grange":              "ferme",
    "manoir":              "manoir",
    "mas":                 "domaine",
    "bastide":             "domaine",
    "clos":                "domaine",
    "abbaye":              "atypique",
    "moulin":              "atypique",
    "orangerie":           "atypique",
    "hotel particulier":   "atypique",
    "atypique":            "atypique",
}

DEFAULT_REGIONS = [
    "Provence-Alpes-Côte d'Azur",
    "Normandie",
    "Centre-Val de Loire",
    "Nouvelle-Aquitaine",
]

REGION_DEPTS = {
    "Auvergne-Rhône-Alpes":       {"01", "03", "07", "15", "26", "38", "42", "43", "63", "69", "73", "74"},
    "Bourgogne-Franche-Comté":    {"21", "25", "39", "58", "70", "71", "89", "90"},
    "Bretagne":                   {"22", "29", "35", "56"},
    "Centre-Val de Loire":        {"18", "28", "36", "37", "41", "45"},
    "Corse":                      {"2A", "2B", "20"},
    "Grand Est":                  {"08", "10", "51", "52", "54", "55", "57", "67", "68", "88"},
    "Hauts-de-France":            {"02", "59", "60", "62", "80"},
    "Île-de-France":              {"75", "77", "78", "91", "92", "93", "94", "95"},
    "Normandie":                  {"14", "27", "50", "61", "76"},
    "Nouvelle-Aquitaine":         {"16", "17", "19", "23", "24", "33", "40", "47", "64", "79", "86", "87"},
    "Occitanie":                  {"09", "11", "12", "30", "31", "32", "34", "46", "48", "65", "66", "81", "82"},
    "Pays de la Loire":           {"44", "49", "53", "72", "85"},
    "Provence-Alpes-Côte d'Azur": {"04", "05", "06", "13", "83", "84"},
}

# Domains that are directories/aggregators/social media — never official venue sites
DIRECTORY_DOMAINS = (
    "mariages.net", "1001salles.com", "abcsalles.com", "wedify",
    "facebook.com", "instagram.com", "tripadvisor", "pagesjaunes.fr",
    "leboncoin", "google.com", "booking.com", "airbnb",
)

WEDDING_TERMS = ("mariage", "wedding", "reception", "ceremonie", "evenement", "seminaire", "celebration")

# Tokens too generic to prove a website belongs to a specific venue
GENERIC_NAME_TOKENS = {
    "chateau", "domaine", "salle", "ferme", "manoir", "moulin", "abbaye",
    "le", "la", "les", "de", "du", "des", "et", "saint", "sainte",
}

MAX_ROUNDS = 3


def normalize_text(value: str) -> str:
    """Accent-strips and lowercases a string for fuzzy comparisons."""
    value = unicodedata.normalize('NFKD', value).encode('ascii', 'ignore').decode('ascii')
    return value.lower().strip()


def normalize_domain(url: str) -> str:
    """Extracts a comparable domain from a URL: netloc, lowercase, without 'www.'."""
    url = (url or "").strip()
    if not url:
        return ""
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    netloc = urlparse(url).netloc.lower()
    return netloc[4:] if netloc.startswith("www.") else netloc


def normalize_type(raw: str) -> str | None:
    """Maps a raw venue type string to a canonical CSV type, or None if unknown."""
    norm = normalize_text(raw)
    if norm in TYPE_ALIASES:
        return TYPE_ALIASES[norm]
    first_word = norm.split(" ")[0] if norm else ""
    return TYPE_ALIASES.get(first_word)


def build_exclusion_sets(rows: list[dict]) -> tuple[set[str], set[str]]:
    """Builds dedup sets (name slugs, website domains) from existing CSV rows."""
    slugs = {slugify(r["name"]) for r in rows if r.get("name")}
    domains = {normalize_domain(r["website"]) for r in rows if r.get("website")}
    domains.discard("")
    return slugs, domains


def build_seed_prompt(region: str, count: int, exclude_names: list[str]) -> str:
    """Builds the grounded research prompt for one region batch."""
    depts = ", ".join(sorted(REGION_DEPTS[region]))
    excluded = "\n".join(f"- {n}" for n in exclude_names) or "- (none)"
    return (
        f'You are researching wedding reception venues in the French region "{region}".\n'
        f"Using Google Search, find {count} real, currently-operating venues that host wedding "
        f"receptions (châteaux, domaines, salles de réception, fermes, manoirs, lieux atypiques).\n\n"
        f"For EACH venue, list on one line all of:\n"
        f"1. Official name\n"
        f"2. City or commune\n"
        f"3. Two-digit department code — it MUST be one of: {depts}\n"
        f'4. Region — exactly "{region}"\n'
        f"5. Type — exactly one of: château, domaine, salle, ferme, manoir, atypique\n"
        f"6. The venue's OFFICIAL website URL — never a directory listing (mariages.net, "
        f"1001salles, abcsalles…), never a Facebook/Instagram page, never a Google Maps link. "
        f"Skip venues that do not have their own website.\n\n"
        f"Do NOT include any of these already-known venues:\n{excluded}\n\n"
        f"Answer as a plain numbered list, one venue per line with all six fields."
    )


def call_gemini_with_retry(client: genai.Client, model: str, contents, config, label: str) -> str | None:
    """Calls generate_content with the shared 3-attempt retry and 429 cooldown."""
    max_retries = 3
    for attempt in range(max_retries):
        try:
            logger.debug(f"Calling Gemini ({label}, attempt {attempt + 1}/{max_retries})...")
            response = client.models.generate_content(model=model, contents=contents, config=config)
            return response.text
        except Exception as e:
            logger.warning(f"Gemini call failed ({label}, attempt {attempt + 1}/{max_retries}): {e}")
            if attempt < max_retries - 1:
                if "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e):
                    console.print("[yellow]⚠️  Gemini Rate Limit (429) hit. Pausing for 30 seconds to cool down...[/yellow]")
                    time.sleep(30)
                else:
                    time.sleep(3 * (attempt + 1))
            else:
                return None


def generate_candidates(client: genai.Client, region: str, count: int,
                        exclude_names: list[str], model: str) -> list[VenueCandidate]:
    """Two-step Gemini sourcing: grounded research, then structured extraction."""
    # Step 1: grounded free-text research (google_search tool is incompatible
    # with response_schema on gemini-2.5-flash, so no structured output here)
    research = call_gemini_with_retry(
        client, model,
        contents=build_seed_prompt(region, count, exclude_names),
        config=types.GenerateContentConfig(
            tools=[types.Tool(google_search=types.GoogleSearch())],
            temperature=0.4,
        ),
        label="grounded research",
    )
    if not research:
        return []
    logger.debug(f"Grounded research output for {region}:\n{research}")

    # Step 2: structure the research notes into JSON (no tools)
    structuring_prompt = (
        "Convert the following venue research notes into structured JSON. "
        "Output every venue mentioned. Copy fields verbatim; 'department' must be "
        "the 2-digit code as a string; 'type' must be one of: château, domaine, "
        "salle, ferme, manoir, atypique.\n\n" + research
    )
    raw = call_gemini_with_retry(
        client, model,
        contents=structuring_prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=list[VenueCandidate],
            temperature=0.1,
        ),
        label="structuring",
    )
    if not raw:
        return []
    try:
        return [VenueCandidate(**item) for item in json.loads(raw)]
    except Exception as e:
        logger.warning(f"Failed to parse structured candidates for {region}: {e}")
        return []


def sanity_check(cand: VenueCandidate, region: str) -> str | None:
    """Returns a rejection reason for a candidate, or None if it passes."""
    if not cand.name.strip() or not cand.city.strip() or not cand.website.strip():
        return "Missing Fields"
    if normalize_type(cand.type) is None:
        return "Bad Type"
    if cand.department.strip() not in REGION_DEPTS[region]:
        return "Bad Dept"
    domain = normalize_domain(cand.website)
    if not domain or any(pat in domain for pat in DIRECTORY_DOMAINS):
        return "Directory URL"
    return None


def load_homepage(page, website_url: str) -> bool:
    """Navigates to the venue homepage, retrying over http if https fails."""
    url = website_url.strip()
    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    try:
        page.goto(url, wait_until="domcontentloaded", timeout=25000)
        page.wait_for_timeout(2000)
        return True
    except Exception as e:
        if url.startswith("https://"):
            try:
                url_http = url.replace("https://", "http://")
                logger.debug(f"Https failed ({e}). Retrying with http: {url_http}")
                page.goto(url_http, wait_until="domcontentloaded", timeout=25000)
                page.wait_for_timeout(2000)
                return True
            except Exception as e2:
                logger.warning(f"Failed to load site {url}: {e2}")
                return False
        logger.warning(f"Failed to load site {url}: {e}")
        return False


def validate_website(page, cand: VenueCandidate) -> tuple[bool, str]:
    """Checks that the candidate's website loads and plausibly matches the venue."""
    if not load_homepage(page, cand.website):
        return False, "Load Failed"

    try:
        body_text = page.evaluate("() => document.body ? document.body.innerText.slice(0, 8000) : ''")
        haystack = normalize_text((page.title() or "") + " " + (body_text or ""))
    except Exception as e:
        logger.warning(f"Failed to read page content for {cand.name}: {e}")
        return False, "Load Failed"

    name_tokens = [t for t in slugify(cand.name).split("_")
                   if len(t) >= 4 and t not in GENERIC_NAME_TOKENS]
    name_hit = any(t in haystack for t in name_tokens)
    wedding_hit = any(term in haystack for term in WEDDING_TERMS)

    if name_hit or wedding_hit:
        return True, "name+wedding" if (name_hit and wedding_hit) else ("name" if name_hit else "wedding")
    return False, "Content Mismatch"


def build_row(cand: VenueCandidate, fieldnames: list[str]) -> dict:
    """Builds a full CSV row for an accepted candidate, enrichment columns empty."""
    website = cand.website.strip()
    if not website.startswith(("http://", "https://")):
        website = "https://" + website
    row = {f: "" for f in fieldnames}
    row.update({
        "name":           cand.name.strip(),
        "city":           cand.city.strip(),
        "department":     cand.department.strip(),
        "region":         cand.region.strip(),
        "type":           normalize_type(cand.type),
        "website":        website,
        "email_verified": "unchecked",
    })
    return row


def write_csv(rows: list[dict], fieldnames: list[str]) -> None:
    with open(CSV_PATH, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def seed_region(client, context, region: str, target: int, dry_run: bool,
                rows: list[dict], fieldnames: list[str], model: str,
                slugs: set[str], domains: set[str]) -> list[tuple]:
    """Runs the candidate/validation rounds for one region; returns summary tuples."""
    results = []
    accepted = 0
    proposed_names = [r["name"] for r in rows if r.get("region", "").lower() == region.lower()]

    for round_idx in range(1, MAX_ROUNDS + 1):
        remaining = target - accepted
        if remaining <= 0:
            break
        ask = min(2 * remaining, 40)
        console.print(f"[cyan]Round {round_idx}/{MAX_ROUNDS} for {region}: asking Gemini for {ask} candidates "
                      f"({accepted}/{target} added)...[/cyan]")
        candidates = generate_candidates(client, region, ask, proposed_names, model)
        if not candidates:
            console.print(f"[red]❌ Gemini returned no candidates for {region} (round {round_idx}). Aborting region.[/red]")
            logger.error(f"No candidates returned for {region} round {round_idx}.")
            break
        logger.info(f"Round {round_idx} for {region}: {len(candidates)} candidates returned.")

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            console=console
        ) as progress:
            task = progress.add_task(f"[cyan]Validating {region}...", total=len(candidates))

            for cand in candidates:
                proposed_names.append(cand.name)
                progress.update(task, description=f"[cyan]Validating: {cand.name}")

                slug = slugify(cand.name)
                domain = normalize_domain(cand.website)
                if slug in slugs or (domain and domain in domains):
                    progress.console.print(f"[yellow]⚠️  {cand.name:35s} -> Duplicate[/yellow]")
                    results.append((cand, "Duplicate"))
                    progress.advance(task)
                    continue

                reason = sanity_check(cand, region)
                if reason:
                    progress.console.print(f"[yellow]⚠️  {cand.name:35s} -> {reason}[/yellow]")
                    results.append((cand, reason))
                    progress.advance(task)
                    continue

                page = context.new_page()
                page.set_default_timeout(25000)
                try:
                    ok, detail = validate_website(page, cand)
                finally:
                    page.close()
                if not ok:
                    progress.console.print(f"[red]❌ {cand.name:35s} -> {detail}[/red]")
                    results.append((cand, detail))
                    progress.advance(task)
                    continue

                rows.append(build_row(cand, fieldnames))
                slugs.add(slug)
                domains.add(domain)
                accepted += 1
                if not dry_run:
                    write_csv(rows, fieldnames)
                progress.console.print(f"[green]✅ {cand.name:35s} -> Added ({cand.city}, {cand.department}, match: {detail})[/green]")
                logger.info(f"Added venue: {cand.name} ({cand.city}, {cand.department}, {region})")
                results.append((cand, "Added"))
                progress.advance(task)

                if accepted >= target:
                    break

    if accepted < target:
        console.print(Panel(
            f"[yellow]Added {accepted}/{target} venues for {region} after {MAX_ROUNDS} rounds.[/yellow]",
            border_style="yellow"
        ))
    return results


def main():
    parser = argparse.ArgumentParser(description="Seed new wedding venues into venues.csv via grounded Gemini search.")
    parser.add_argument("--region", type=str, default=None, help="Region to seed (must be a known metropolitan region).")
    parser.add_argument("--all-defaults", action="store_true", help="Seed the default target regions sequentially.")
    parser.add_argument("--target", type=int, default=25, help="Venues to add per region after validation (default 25).")
    parser.add_argument("--dry-run", action="store_true", help="Validate fully but write nothing.")
    parser.add_argument("--model", type=str, default="gemini-2.5-flash", help="Gemini model to use.")
    args = parser.parse_args()

    load_dotenv()
    load_dotenv(dotenv_path="backend/.env")

    Path("logs").mkdir(parents=True, exist_ok=True)

    console.print(Panel.fit(
        "[bold magenta]Autocaller Venue Seeder[/bold magenta]\n"
        "[dim]Gemini grounded search + Playwright validation[/dim]",
        border_style="magenta"
    ))

    if not args.region and not args.all_defaults:
        console.print("[bold red]Error: provide --region NAME or --all-defaults.[/bold red]")
        sys.exit(1)
    if args.region and args.region not in REGION_DEPTS:
        console.print(f"[bold red]Error: unknown region '{args.region}'.[/bold red]")
        console.print("Valid regions: " + ", ".join(sorted(REGION_DEPTS)))
        sys.exit(1)

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        console.print("[bold red]Error: GEMINI_API_KEY environment variable is not set in environment or .env file.[/bold red]")
        logger.error("GEMINI_API_KEY not found.")
        sys.exit(1)
    client = genai.Client(api_key=api_key)

    if not CSV_PATH.exists():
        console.print(f"[bold red]Error: CSV file not found at {CSV_PATH}[/bold red]")
        sys.exit(1)

    with open(CSV_PATH, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        fieldnames = list(reader.fieldnames)
        rows = list(reader)

    slugs, domains = build_exclusion_sets(rows)
    regions = DEFAULT_REGIONS if args.all_defaults else [args.region]
    all_results = []

    with sync_playwright() as p:
        logger.debug("Starting browser context...")
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 800},
            ignore_https_errors=True
        )
        for region in regions:
            all_results.extend(
                seed_region(client, context, region, args.target, args.dry_run,
                            rows, fieldnames, args.model, slugs, domains)
            )
        browser.close()

    # Summary Table
    table = Table(title="Venue Seeding Summary", show_header=True, header_style="bold magenta")
    table.add_column("Venue", style="dim")
    table.add_column("City")
    table.add_column("Dept", justify="center")
    table.add_column("Type")
    table.add_column("Website", style="cyan", overflow="fold")
    table.add_column("Status", style="bold")

    for cand, status in all_results:
        color = "green" if status == "Added" else ("yellow" if status in ("Duplicate", "Bad Dept", "Bad Type", "Directory URL", "Missing Fields") else "red")
        table.add_row(cand.name, cand.city, cand.department, cand.type, cand.website, f"[{color}]{status}[/{color}]")

    console.print("\n")
    console.print(table)
    added = sum(1 for _, s in all_results if s == "Added")
    if args.dry_run:
        console.print(Panel(
            f"[bold][dry-run][/bold] {added} venue(s) validated — nothing written.",
            title="Dry Run Complete",
            border_style="yellow"
        ))
    else:
        console.print(Panel(
            f"[bold]{added} venue(s) added. All changes progressively written to:[/bold]\n{CSV_PATH}",
            title="Seeding Complete",
            border_style="magenta"
        ))


if __name__ == "__main__":
    main()
