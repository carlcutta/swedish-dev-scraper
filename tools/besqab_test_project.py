"""Test scrape of a single Besqab project page.

Scrapes the apartment table from a hardcoded URL, saves the result to
data/latest/besqab.json (same format as the main scraper), then the
workflow runs export_csv.py to produce data/latest/apartments.csv.
"""
import asyncio
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse
from playwright.async_api import async_playwright

URL = "https://www.besqab.se/stockholm/danderyd/hertha/"

_APT_HEADERS = {"nummer", "v\u00e5ning", "antal rum", "storlek", "pris", "avgift", "status"}


async def scrape_project(url: str) -> dict:
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        ctx = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            locale="sv-SE",
            timezone_id="Europe/Stockholm",
            extra_http_headers={"Accept-Language": "sv-SE,sv;q=0.9"},
        )
        await ctx.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', { get: () => undefined });"
        )
        page = await ctx.new_page()

        print(f"Navigating to: {url}")
        resp = await page.goto(url, wait_until="networkidle", timeout=60000)
        print(f"HTTP status: {resp.status}")
        await asyncio.sleep(2)

        print(f"Page title: {await page.title()}")
        h1 = await page.query_selector("h1")
        name = (await h1.inner_text()).strip() if h1 else ""
        print(f"Project name: {name}")

        apartments = await extract_apartment_table(page)
        print(f"Apartments found: {len(apartments)}")
        for apt in apartments:
            print(f"  {apt}")

        await browser.close()

    segments = [s for s in urlparse(url).path.strip("/").split("/") if s]
    region = segments[0].replace("-", " ").title() if segments else ""
    area   = segments[1].replace("-", " ").title() if len(segments) > 1 else ""
    slug   = segments[-1] if segments else name.lower().replace(" ", "-")

    available = sum(1 for a in apartments if a.get("Status", "").strip().lower() == "till salu")
    sold      = sum(1 for a in apartments if a.get("Status", "").strip().lower() in ("s\u00e5ld", "reserverad"))
    prices    = [_parse_int(a.get("Pris", "")) for a in apartments]
    prices    = [p for p in prices if p]
    fees      = [_parse_int(a.get("Avgift", "")) for a in apartments]
    fees      = [f for f in fees if f]

    project = {
        "id": f"besqab-{slug}",
        "name": name,
        "url": url,
        "location": f"{area}, {region}" if area else region,
        "municipality": area or region,
        "county": region,
        "status": "sold_out" if (apartments and available == 0) else "selling",
        "total_units": len(apartments) or None,
        "available_units": available,
        "sold_units": sold,
        "price_from": min(prices) if prices else None,
        "price_to":   max(prices) if prices else None,
        "monthly_fee_from": min(fees) if fees else None,
        "monthly_fee_to":   max(fees) if fees else None,
        "apartments": apartments,
    }

    return {
        "developer": "Besqab",
        "developer_url": "https://www.besqab.se",
        "scraped_at": datetime.now(timezone.utc).isoformat(),
        "project_count": 1,
        "error": None,
        "projects": [project],
    }


async def extract_apartment_table(page) -> list[dict]:
    return await page.evaluate("""
        (aptHeaders) => {
            const tables = Array.from(document.querySelectorAll('table'));
            if (!tables.length) return [];

            let bestTable = null, bestScore = 0;
            for (const tbl of tables) {
                const thEls = tbl.querySelectorAll('thead th, thead td');
                const firstRow = tbl.querySelector('tr');
                const headerEls = thEls.length
                    ? Array.from(thEls)
                    : firstRow ? Array.from(firstRow.querySelectorAll('th,td')) : [];
                const headers = headerEls.map(el => el.innerText.trim().toLowerCase());
                const score = headers.filter(h => aptHeaders.includes(h)).length;
                if (score > bestScore) { bestScore = score; bestTable = tbl; }
            }
            if (!bestTable || bestScore < 2) return [];

            const thEls = bestTable.querySelectorAll('thead th, thead td');
            const firstRow = bestTable.querySelector('tr');
            const headerEls = thEls.length
                ? Array.from(thEls)
                : firstRow ? Array.from(firstRow.querySelectorAll('th,td')) : [];
            const headers = headerEls.map(el => el.innerText.trim());

            const bodyRows = bestTable.querySelectorAll('tbody tr');
            const dataRows = bodyRows.length
                ? Array.from(bodyRows)
                : Array.from(bestTable.querySelectorAll('tr')).slice(1);

            return dataRows.map(row => {
                const cells = Array.from(row.querySelectorAll('td,th'));
                if (!cells.some(c => c.innerText.trim())) return null;
                const obj = {};
                cells.forEach((cell, i) => { obj[headers[i] || ('col_' + i)] = cell.innerText.trim(); });
                return obj;
            }).filter(Boolean);
        }
    """, list(_APT_HEADERS))


def _parse_int(val: str):
    cleaned = re.sub(r"[^\d]", "", str(val))
    return int(cleaned) if cleaned else None


if __name__ == "__main__":
    snapshot = asyncio.run(scrape_project(URL))

    out = Path("data/latest/besqab.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nSaved to {out}")
