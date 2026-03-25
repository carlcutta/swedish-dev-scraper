"""Scraper for Besqab - besqab.se

Strategy:
  1. Crawl besqab.se to discover project URLs (3-segment paths like
     /stockholm/danderyd/hertha/).
  2. For each project page, locate the standard <table> that contains
     the apartment listing with headers:
       Nummer | V\u00e5ning | Antal rum | Storlek | Pris | Avgift | Status
  3. Return one Project per project page; apartments with status
     \u201cTill salu\u201d are counted as available.
"""
import asyncio
import re
from urllib.parse import urlparse
from playwright.async_api import Browser, Page
from ..base import BaseScraper
from ..models import Project


BASE_URL = "https://www.besqab.se"

_NAV_SLUGS = {
    "kontakt", "om-oss", "om-besqab", "hallbarhet", "h\u00e5llbarhet",
    "investerare", "press", "karriar", "karri\u00e4r", "nyheter",
    "integritetspolicy", "cookies", "sitemap", "search", "s\u00f6k", "404",
    "gdpr", "tillganglighetsredogorelse",
}

# Known apartment-table header words (lowercase) — used to pick the right table
_APT_HEADERS = {"nummer", "v\u00e5ning", "antal rum", "storlek", "pris", "avgift", "status"}


class BesqabScraper(BaseScraper):
    name = "Besqab"
    url = BASE_URL

    async def scrape(self, browser: Browser) -> list:
        ctx = await self._new_context(browser)
        page = await ctx.new_page()
        projects = []

        try:
            project_urls = await _discover_project_urls(page)
            print(f"[Besqab] Discovered {len(project_urls)} project URLs")

            for url in project_urls:
                try:
                    project = await _scrape_project(page, url)
                    if project:
                        projects.append(project)
                        print(
                            f"[Besqab] {project.name}: "
                            f"{len(project.apartments)} apartments, "
                            f"{project.available_units} available"
                        )
                except Exception as exc:
                    print(f"[Besqab] Error scraping {url}: {exc}")
        finally:
            await ctx.close()

        print(f"[Besqab] Done \u2014 {len(projects)} projects")
        return projects


# ── Discovery ───────────────────────────────────────────────────────────────────────────────────

async def _discover_project_urls(page: Page) -> list[str]:
    """
    Walk besqab.se breadth-first from the root and a set of seeded
    paths. Collect all URLs with exactly 3 path segments — those are
    individual project pages.
    Waits for networkidle on each page so JS-rendered links load.
    """
    visited: set[str] = set()
    project_urls: set[str] = set()
    to_visit: list[str] = [
        BASE_URL + "/",
        BASE_URL + "/stockholm/",
        BASE_URL + "/uppsala/",
        BASE_URL + "/vastmanland/",
        BASE_URL + "/vara-projekt/",
        BASE_URL + "/projekt/",
        BASE_URL + "/bostader/",
    ]

    while to_visit:
        url = to_visit.pop(0)
        if url in visited:
            continue
        visited.add(url)

        try:
            await page.goto(url, wait_until="networkidle", timeout=45000)
            await asyncio.sleep(1.5)
        except Exception:
            continue

        links: list[str] = await page.eval_on_selector_all(
            "a[href]", "els => els.map(e => e.href)"
        )

        for link in links:
            norm = _normalize(link)
            if not norm or norm in visited:
                continue
            d = _depth(norm)
            if d == 3:
                project_urls.add(norm)
            elif d in (1, 2) and norm not in to_visit:
                to_visit.append(norm)

    return sorted(project_urls)


def _normalize(url: str) -> str | None:
    try:
        p = urlparse(url)
    except Exception:
        return None
    if p.netloc not in ("www.besqab.se", "besqab.se"):
        return None
    path = p.path.rstrip("/") + "/"
    segments = [s for s in path.strip("/").split("/") if s]
    if not segments:
        return None
    if any(s in _NAV_SLUGS for s in segments):
        return None
    if re.search(r"\.[a-z]{2,4}$", segments[-1]):
        return None
    return f"https://www.besqab.se{path}"


def _depth(url: str) -> int:
    return len([s for s in urlparse(url).path.strip("/").split("/") if s])


# ── Per-project scraping ─────────────────────────────────────────────────────────────────────

async def _scrape_project(page: Page, url: str) -> Project | None:
    await page.goto(url, wait_until="networkidle", timeout=60000)
    await asyncio.sleep(1.5)

    h1 = await page.query_selector("h1")
    name = (await h1.inner_text()).strip() if h1 else ""
    if not name:
        name = (await page.title()).split("|")[0].split("-")[0].strip()
    if not name:
        return None

    segments = [s for s in urlparse(url).path.strip("/").split("/") if s]
    region = segments[0].replace("-", " ").title() if segments else ""
    area = segments[1].replace("-", " ").title() if len(segments) > 1 else ""
    location = f"{area}, {region}" if area else region
    slug = segments[-1] if segments else re.sub(r"[^a-z0-9]+", "-", name.lower())

    apartments = await _extract_apartment_table(page)

    available = sum(1 for a in apartments if a.get("Status", "").strip().lower() == "till salu")
    sold = sum(1 for a in apartments if a.get("Status", "").strip().lower() in ("s\u00e5ld", "sold", "reserverad"))
    total = len(apartments) or None

    prices = [_parse_int(a.get("Pris", "")) for a in apartments]
    prices = [p for p in prices if p]
    fees = [_parse_int(a.get("Avgift", "")) for a in apartments]
    fees = [f for f in fees if f]

    status = "sold_out" if (total and available == 0) else "selling"

    return Project(
        developer="Besqab",
        id=f"besqab-{slug}",
        name=name,
        url=url,
        location=location,
        municipality=area or region,
        county=region,
        status=status,
        total_units=total,
        available_units=available if apartments else None,
        sold_units=sold if apartments else None,
        price_from=min(prices) if prices else None,
        price_to=max(prices) if prices else None,
        monthly_fee_from=min(fees) if fees else None,
        monthly_fee_to=max(fees) if fees else None,
        apartments=apartments,
    )


# ── Table extraction ─────────────────────────────────────────────────────────────────────────────────

async def _extract_apartment_table(page: Page) -> list[dict]:
    """
    Find the <table> whose headers include the known apartment columns
    (Nummer, V\u00e5ning, Antal rum, Storlek, Pris, Avgift, Status) and
    return every row as a dict keyed by the exact header text.
    """
    return await page.evaluate("""
        (aptHeaders) => {
            const tables = Array.from(document.querySelectorAll('table'));
            if (!tables.length) return [];

            // Pick the table whose headers overlap most with our known headers
            let bestTable = null;
            let bestScore = 0;

            for (const tbl of tables) {
                const thEls = tbl.querySelectorAll('thead th, thead td');
                const firstRow = tbl.querySelector('tr');
                const headerEls = thEls.length
                    ? Array.from(thEls)
                    : firstRow ? Array.from(firstRow.querySelectorAll('th, td')) : [];
                const headers = headerEls.map(el => el.innerText.trim().toLowerCase());
                const score = headers.filter(h => aptHeaders.includes(h)).length;
                if (score > bestScore) {
                    bestScore = score;
                    bestTable = tbl;
                }
            }

            if (!bestTable || bestScore < 2) return [];

            // Extract headers (preserve original casing for output)
            const thEls = bestTable.querySelectorAll('thead th, thead td');
            const firstRow = bestTable.querySelector('tr');
            const headerEls = thEls.length
                ? Array.from(thEls)
                : firstRow ? Array.from(firstRow.querySelectorAll('th, td')) : [];
            const headers = headerEls.map(el => el.innerText.trim());

            // Extract data rows
            const bodyRows = bestTable.querySelectorAll('tbody tr');
            const dataRows = bodyRows.length
                ? Array.from(bodyRows)
                : Array.from(bestTable.querySelectorAll('tr')).slice(1);

            return dataRows.map(row => {
                const cells = Array.from(row.querySelectorAll('td, th'));
                if (!cells.some(c => c.innerText.trim())) return null;
                const obj = {};
                cells.forEach((cell, i) => {
                    obj[headers[i] || ('col_' + i)] = cell.innerText.trim();
                });
                return obj;
            }).filter(Boolean);
        }
    """, list(_APT_HEADERS))


# ── Helpers ───────────────────────────────────────────────────────────────────────────────────────

def _parse_int(val: str) -> int | None:
    cleaned = re.sub(r"[^\d]", "", str(val))
    if cleaned:
        try:
            return int(cleaned)
        except Exception:
            pass
    return None
