#!/usr/bin/env python3
"""
Scrapes a representative photo URL for each wedding venue website.

This script processes wedding venues listed in 'venues.csv'. For each venue:
  1. It launches a headless Playwright browser tab and navigates to the homepage.
  2. It extracts a photo URL in priority order:
       a. <meta property="og:image">
       b. <meta name="twitter:image">
       c. The largest rendered <img> on the page (min 400x250, skipping logos/data-URIs).
  3. It writes the resolved absolute URL into a 'photo_url' column in 'venues.csv',
     saving progressively after each venue.

No Gemini calls and no screenshots — Playwright only.

Execution:
  uv run python scripts/scrape_photos.py [options]

Options:
  --force       Process all venues, even if they already have a photo_url.
  --limit N     Limit the execution to processing N venues.
  --venue NAME  Process only a specific venue by name (case-insensitive).
"""

import csv
import sys
import argparse
from pathlib import Path
from urllib.parse import urljoin

# Reconfigure stdout/stderr to UTF-8 to prevent encoding crashes on Windows console
try:
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
except Exception:
    pass

from loguru import logger
from playwright.sync_api import sync_playwright
from rich.console import Console
from rich.panel import Panel
from rich.progress import BarColumn, Progress, SpinnerColumn, TaskProgressColumn, TextColumn
from rich.table import Table

console = Console()

# Configure loguru: Log only to file, disable stdout output
logger.remove()
logger.add("logs/photo_scraper.log", rotation="10 MB", level="DEBUG", encoding="utf-8")

CSV_PATH = Path(__file__).parent.parent / "venues.csv"

MIN_WIDTH = 400
MIN_HEIGHT = 250

# Filename fragments that indicate a non-photo asset (logos, icons, sprites)
SKIP_PATTERNS = ("logo", "icon", "sprite", "favicon", "badge", "placeholder")

# JS evaluated in the page to pick the largest rendered image
LARGEST_IMG_JS = """
() => {
  const imgs = Array.from(document.querySelectorAll('img'));
  let best = null;
  let bestArea = 0;
  for (const img of imgs) {
    const src = img.currentSrc || img.src || '';
    if (!src || src.startsWith('data:')) continue;
    const w = img.naturalWidth, h = img.naturalHeight;
    if (w * h > bestArea) { bestArea = w * h; best = { src, w, h }; }
  }
  return best;
}
"""


def extract_photo_url(page) -> str | None:
    """Extracts a representative photo URL from the current page, best source first."""
    for selector, attr in (
        ('meta[property="og:image"]', "content"),
        ('meta[name="twitter:image"]', "content"),
    ):
        el = page.query_selector(selector)
        if el:
            src = (el.get_attribute(attr) or "").strip()
            if src and not src.startswith("data:"):
                logger.debug(f"Found meta image via {selector}: {src}")
                return urljoin(page.url, src)

    candidate = page.evaluate(LARGEST_IMG_JS)
    if candidate and candidate["w"] >= MIN_WIDTH and candidate["h"] >= MIN_HEIGHT:
        src = candidate["src"]
        if not any(pat in src.lower() for pat in SKIP_PATTERNS):
            logger.debug(f"Found largest rendered image ({candidate['w']}x{candidate['h']}): {src}")
            return urljoin(page.url, src)

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


def main():
    parser = argparse.ArgumentParser(description="Scrape venue photo URLs using Playwright.")
    parser.add_argument("--force", action="store_true", help="Process all venues even if photo_url already exists.")
    parser.add_argument("--limit", type=int, default=None, help="Limit the number of venues to process.")
    parser.add_argument("--venue", type=str, default=None, help="Process only a specific venue by name.")
    args = parser.parse_args()

    Path("logs").mkdir(parents=True, exist_ok=True)

    console.print(Panel.fit(
        "[bold magenta]Autocaller Photo Scraper[/bold magenta]\n"
        "[dim]og:image / twitter:image / largest rendered photo[/dim]",
        border_style="magenta"
    ))

    if not CSV_PATH.exists():
        console.print(f"[bold red]Error: CSV file not found at {CSV_PATH}[/bold red]")
        logger.error(f"CSV file not found at {CSV_PATH}")
        sys.exit(1)

    with open(CSV_PATH, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        fieldnames = list(reader.fieldnames)
        rows = list(reader)

    # Support photo_url column
    if "photo_url" not in fieldnames:
        fieldnames.append("photo_url")

    # Filter venues to process
    to_process = []
    for row in rows:
        name = row["name"]
        if args.venue and args.venue.lower() not in name.lower():
            continue
        if row.get("photo_url") and not args.force and not args.venue:
            continue
        to_process.append(row)

    if args.limit:
        to_process = to_process[:args.limit]

    logger.info(f"Selected {len(to_process)} venues for processing.")

    if not to_process:
        console.print("[yellow]Nothing to process. Use --force to re-process all venues.[/yellow]")
        return

    processed_results = []

    with sync_playwright() as p:
        logger.debug("Starting browser context...")
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 800},
            ignore_https_errors=True
        )
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            console=console
        ) as progress:
            task = progress.add_task("[cyan]Processing venues...", total=len(to_process))

            for original_idx, row in enumerate(to_process, 1):
                name = row["name"]
                website = row["website"]

                progress.update(task, description=f"[cyan]Photo: {name}")
                logger.info(f"Scraping photo [{original_idx}/{len(to_process)}]: {name} ({website})")

                if not website:
                    progress.console.print(f"[yellow]⚠️  [{original_idx}] {name:30s} -> No website URL specified[/yellow]")
                    processed_results.append((name, None, "Skipped (No URL)"))
                    progress.advance(task)
                    continue

                page = context.new_page()
                page.set_default_timeout(25000)
                try:
                    if not load_homepage(page, website):
                        progress.console.print(f"[red]❌ [{original_idx}] {name:30s} -> Could not load website[/red]")
                        processed_results.append((name, None, "Load Failed"))
                        progress.advance(task)
                        continue

                    photo_url = extract_photo_url(page)
                    if photo_url:
                        row["photo_url"] = photo_url
                        progress.console.print(f"[green]✅ [{original_idx}] {name:30s} -> {photo_url[:70]}[/green]")
                        logger.info(f"Photo for {name}: {photo_url}")
                        processed_results.append((name, photo_url, "Scraped"))
                    else:
                        progress.console.print(f"[yellow]⚠️  [{original_idx}] {name:30s} -> No suitable photo found[/yellow]")
                        logger.warning(f"No suitable photo found for {name}")
                        processed_results.append((name, None, "Not Found"))

                    # Save CSV progressively after each attempt to preserve progress
                    with open(CSV_PATH, "w", newline="", encoding="utf-8") as f:
                        writer = csv.DictWriter(f, fieldnames=fieldnames)
                        writer.writeheader()
                        writer.writerows(rows)
                    logger.debug("Progressively updated CSV.")
                    progress.advance(task)
                finally:
                    page.close()

        browser.close()

    # Summary Table
    table = Table(title="Photo Scraping Summary", show_header=True, header_style="bold magenta")
    table.add_column("Venue", style="dim")
    table.add_column("Photo URL", style="green", overflow="fold")
    table.add_column("Status", style="bold")

    for name, photo_url, status in processed_results:
        color = "green" if status == "Scraped" else ("yellow" if status in ("Not Found", "Skipped (No URL)") else "red")
        table.add_row(name, photo_url or "-", f"[{color}]{status}[/{color}]")

    console.print("\n")
    console.print(table)
    console.print(Panel(
        f"[bold]All changes progressively written to:[/bold]\n{CSV_PATH}",
        title="Processing Complete",
        border_style="magenta"
    ))


if __name__ == "__main__":
    main()
