"""Scraper for Besqab - besqab.se

Strategy:
  1. Crawl besqab.se from the root to discover project URLs.
     Project pages follow the 3-segment pattern: /region/area/project/
     (e.g. /stockholm/slakthusomradet/fransyskan/)
  2. For each project page, render fully with Playwright, then locate the
     apartment listing table and extract every row as a dict keyed by the
     column header exactly as it appears on the page.
  3. Return one Project per project page with the raw apartment rows attached.
"""
import asyncio
import re
from urllib.parse import urlparse
from playwright.async_api import Browser, Page
from ..base import BaseScraper
from ..models import Project


BASE_URL = "https://www.besqab.se"

# Path segments that identify navigation / utility pages — never project pages.
_NAV_SLUGS = {
    "kontakt", "om-oss", "om-besqab", "hallbarhet", "h\u00e5llbarhet",
    "investerare", "press", "karriar", "karri\u00e4r", "nyheter",
    "integritetspolicy", "cookies", "sitemap", "search", "s\u00f6k", "404",
    "gdpr", "tillganglighetsredogorelse",
}


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

            for project_url in project_urls:
                try:
                    project = await _scrape_project(page, project_url)
                    if project:
                        projects.append(project)
                        print(
                            f"[Besqab] {project.name}: "
                            f"{len(project.apartments)} apartments, "
                            f"{project.available_units} available"
                        )
                except Exception as exc:
                    print(f"[Besqab] Error scraping {project_url}: {exc}")

        finally:
            await ctx.close()

        print(f"[Besqab] Done \u2014 {len(projects)} projects")
        return projects


# ── URL discovery ──────────────────────────────────────────────────────────────────────────────

async def _discover_project_urls(page: Page) -> list[str]:
    """
    Walk besqab.se breadth-first, collecting URLs that are exactly 3 path
    segments deep — those are individual project pages.
    Depth-1 and depth-2 URLs are queued for further crawling.
    """
    visited: set[str] = set()
    project_urls: set[str] = set()

    # Seed: root + known region/listing paths
    to_visit: list[str] = [
        BASE_URL + "/",
        BASE_URL + "/stockholm/",
        BASE_URL + "/uppsala/",
        BASE_URL + "/v\u00e4stmanland/",
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
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            await asyncio.sleep(0.8)
        except Exception:
            continue

        links: list[str] = await page.eval_on_selector_all(
            "a[href]", "els => els.map(e => e.href)"
        )

        for link in links:
            norm = _normalize(link)
            if not norm or norm in visited:
                continue
            depth = _path_depth(norm)
            if depth == 3:
                project_urls.add(norm)
            elif depth in (1, 2) and norm not in to_visit:
                to_visit.append(norm)

    return sorted(project_urls)


def _normalize(url: str) -> str | None:
    """Return a canonical besqab.se URL or None if irrelevant."""
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
    # Skip file-like paths
    if re.search(r"\.[a-z]{2,4}$", segments[-1]):
        return None
    return f"https://www.besqab.se{path}"


def _path_depth(url: str) -> int:
    path = urlparse(url).path
    return len([s for s in path.strip("/").split("/") if s])


# ── Per-project scraping ───────────────────────────────────────────────────────────────────

async def _scrape_project(page: Page, url: str) -> Project | None:
    """Navigate to a project page and extract name + full apartment table."""
    await page.goto(url, wait_until="networkidle", timeout=60000)
    await asyncio.sleep(1.5)

    # Project name
    h1 = await page.query_selector("h1")
    name = (await h1.inner_text()).strip() if h1 else ""
    if not name:
        title = await page.title()
        name = title.split("|")[0].split("-")[0].strip()
    if not name:
        return None

    # Location from URL segments
    segments = [s for s in urlparse(url).path.strip("/").split("/") if s]
    region = segments[0].replace("-", " ").title() if segments else ""
    area = segments[1].replace("-", " ").title() if len(segments) > 1 else ""
    location = f"{area}, {region}" if area else region
    slug = segments[-1] if segments else re.sub(r"[^a-z0-9]+", "-", name.lower())

    # Apartment table
    apartments = await _extract_table(page)

    # Summary stats derived from individual apartment rows
    available = sum(1 for a in apartments if _is_available(a))
    sold = sum(1 for a in apartments if _is_sold(a))
    total = len(apartments) or None
    prices = [p for a in apartments for p in [_extract_price(a)] if p]
    fees = [f for a in apartments for f in [_extract_fee(a)] if f]

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


# ── Table extraction ─────────────────────────────────────────────────────────────────────────────

async def _extract_table(page: Page) -> list[dict]:
    """
    Try to find the apartment listing table on the page.
    Tries <table> first, then common div/grid patterns.
    Returns a list of dicts with column headers as keys, exactly as
    they appear on the page (Swedish column names preserved).
    """
    rows = await _extract_html_table(page)
    if rows:
        return rows
    return await _extract_div_table(page)


async def _extract_html_table(page: Page) -> list[dict]:
    """Extract rows from the largest <table> on the page."""
    return await page.evaluate("""
        () => {
            const tables = Array.from(document.querySelectorAll('table'));
            if (!tables.length) return [];

            // Use the table with the most rows
            const best = tables.reduce((a, b) =>
                a.querySelectorAll('tr').length >= b.querySelectorAll('tr').length ? a : b
            );
            const allRows = Array.from(best.querySelectorAll('tr'));
            if (allRows.length < 2) return [];

            // Headers: prefer <thead>, else first <tr>
            const theadCells = best.querySelectorAll('thead th, thead td');
            const headers = theadCells.length
                ? Array.from(theadCells).map(el => el.innerText.trim())
                : Array.from(allRows[0].querySelectorAll('th, td')).map(el => el.innerText.trim());

            const bodyRows = best.querySelectorAll('tbody tr');
            const dataRows = bodyRows.length ? Array.from(bodyRows) : allRows.slice(1);

            return dataRows.map(row => {
                const cells = Array.from(row.querySelectorAll('td, th'));
                if (!cells.length) return null;
                const obj = {};
                cells.forEach((cell, i) => {
                    const key = headers[i] || ('col_' + i);
                    obj[key] = cell.innerText.trim();
                });
                return obj;
            }).filter(Boolean);
        }
    """) or []


async def _extract_div_table(page: Page) -> list[dict]:
    """
    Fallback for CSS-grid / div-based apartment lists.
    Looks for a container whose class name suggests an apartment list,
    then treats child elements as rows.
    """
    return await page.evaluate("""
        () => {
            const selectors = [
                '[class*="apartment"]', '[class*="Apartment"]',
                '[class*="bostad"]',    '[class*="Bostad"]',
                '[class*="unit-list"]', '[class*="UnitList"]',
                '[class*="home-list"]', '[class*="HomeList"]',
                '[class*="listing"]',   '[class*="Listing"]',
                '[class*="lagenh"]',    '[class*="object-list"]',
            ];
            let container = null;
            for (const sel of selectors) {
                const el = document.querySelector(sel);
                if (el && el.children.length > 1) { container = el; break; }
            }
            if (!container) return [];

            const rows = Array.from(container.children);
            if (rows.length < 2) return [];

            const headers = Array.from(rows[0].children).map(el => el.innerText.trim());
            if (!headers.some(h => h)) return [];

            return rows.slice(1).map(row => {
                const cells = Array.from(row.children);
                if (!cells.length) return null;
                const obj = {};
                cells.forEach((cell, i) => {
                    obj[headers[i] || ('col_' + i)] = cell.innerText.trim();
                });
                return obj;
            }).filter(Boolean);
        }
    """) or []


# ── Helpers ──────────────────────────────────────────────────────────────────────────────────────

def _is_available(apt: dict) -> bool:
    for key, val in apt.items():
        if any(k in key.lower() for k in ["status", "tillg", "ledig"]):
            v = str(val).lower()
            if any(k in v for k in ["tillgänglig", "ledig", "available", "till salu"]):
                return True
    return False


def _is_sold(apt: dict) -> bool:
    for key, val in apt.items():
        if any(k in key.lower() for k in ["status", "såld", "sold"]):
            v = str(val).lower()
            if any(k in v for k in ["såld", "sold", "reserverad", "reserved"]):
                return True
    return False


def _extract_price(apt: dict) -> int | None:
    for key, val in apt.items():
        if any(k in key.lower() for k in ["pris", "price", "kr", "kpris"]):
            cleaned = re.sub(r"[^\d]", "", str(val))
            if cleaned and len(cleaned) >= 4:
                try:
                    return int(cleaned)
                except Exception:
                    pass
    return None


def _extract_fee(apt: dict) -> int | None:
    for key, val in apt.items():
        if any(k in key.lower() for k in ["avgift", "fee", "mån", "månadskostnad"]):
            cleaned = re.sub(r"[^\d]", "", str(val))
            if cleaned:
                try:
                    return int(cleaned)
                except Exception:
                    pass
    return None
