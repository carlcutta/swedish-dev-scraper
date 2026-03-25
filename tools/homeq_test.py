"""Test script: scrape page 1 of Juli Living apartments from HomeQ.

Run from the repo root:
    python tools/homeq_test.py

Fetches only the first page of https://www.homeq.se/p/nrep (no pagination).
For each apartment listing found, visits the detail page and prints all fields
under the "Uthyrningsdetaljer" heading.

Results are also saved to data/homeq_test_<timestamp>.json.

Set HEADLESS=0 to watch the browser in action (Mac/Linux with display):
    HEADLESS=0 python tools/homeq_test.py
"""
import asyncio
import json
import os
import random
import sys
from datetime import datetime, timezone
from pathlib import Path

from playwright.async_api import async_playwright

BASE_URL = "https://www.homeq.se/p/nrep"
HEADLESS = os.environ.get("HEADLESS", "1") != "0"

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
]


async def main():
    print(f"HomeQ / Juli Living — page-1 test")
    print(f"URL: {BASE_URL}")
    print(f"Headless: {HEADLESS}")
    print("=" * 60)

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=HEADLESS)
        ctx = await browser.new_context(
            user_agent=random.choice(USER_AGENTS),
            viewport={"width": 1440, "height": 900},
            locale="sv-SE",
            timezone_id="Europe/Stockholm",
            extra_http_headers={
                "Accept-Language": "sv-SE,sv;q=0.9,en-GB;q=0.8,en;q=0.7",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
                "DNT": "1",
            },
        )
        await ctx.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            Object.defineProperty(navigator, 'plugins', { get: () => [1,2,3,4,5] });
            window.chrome = { runtime: {} };
        """)
        page = await ctx.new_page()

        # ── Step 1: Load the NREP profile page ──────────────────────────────
        print(f"\n[1/3] Loading {BASE_URL} ...")
        await page.goto(BASE_URL, wait_until="networkidle", timeout=90000)
        await asyncio.sleep(2)

        title = await page.title()
        print(f"      Page title: {title}")

        # ── Step 2: Collect listing URLs from page 1 ─────────────────────────
        print("\n[2/3] Collecting apartment listing URLs ...")
        listing_urls = await _extract_listing_urls(page)

        if not listing_urls:
            print("\n  No listing URLs found — dumping page for inspection:")
            _dump_debug(await page.content(), await page.url)
            await browser.close()
            sys.exit(1)

        print(f"  Found {len(listing_urls)} listings:")
        for u in listing_urls:
            print(f"    {u}")

        # ── Step 3: Scrape each apartment detail page ─────────────────────────
        print(f"\n[3/3] Scraping {len(listing_urls)} detail pages ...")
        apartments = []
        for i, url in enumerate(listing_urls, 1):
            print(f"\n  [{i}/{len(listing_urls)}] {url}")
            try:
                apt = await _scrape_apartment(page, url)
                if apt:
                    apartments.append(apt)
                    details = apt.get("uthyrningsdetaljer", {})
                    if details:
                        for k, v in details.items():
                            print(f"    {k}: {v}")
                    else:
                        print("    (no Uthyrningsdetaljer found)")
                else:
                    print("    (no data extracted)")
            except Exception as exc:
                print(f"    ERROR: {exc}")

        await browser.close()

    # ── Output ────────────────────────────────────────────────────────────────
    output = {
        "scraped_at": datetime.now(timezone.utc).isoformat(),
        "source_url": BASE_URL,
        "page": 1,
        "apartment_count": len(apartments),
        "apartments": apartments,
    }

    data_dir = Path(__file__).parent.parent / "data"
    data_dir.mkdir(exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = data_dir / f"homeq_test_{timestamp}.json"
    out_path.write_text(json.dumps(output, ensure_ascii=False, indent=2))

    print(f"\n{'='*60}")
    print(f"Scraped {len(apartments)} apartments from page 1.")
    print(f"Results saved to: {out_path}")
    print(f"{'='*60}\n")
    print(json.dumps(output, ensure_ascii=False, indent=2))


async def _extract_listing_urls(page) -> list[str]:
    """Extract apartment detail page URLs from the current page."""
    urls = await page.evaluate(
        """
        () => {
            const seen = new Set();
            const results = [];
            const links = Array.from(document.querySelectorAll('a[href]'));

            for (const a of links) {
                const href = a.href || '';
                if (!href.includes('homeq.se')) continue;

                // Match known HomeQ detail URL patterns
                if (
                    href.match(/\\/listing\\/\\d+/) ||
                    href.match(/\\/object\\/\\d+/) ||
                    href.match(/\\/bostad\\/\\d+/) ||
                    href.match(/\\/lagenhet\\/\\d+/) ||
                    href.match(/homeq\\.se\\/[a-z]{2,}\\/\\d{4,}/) ||
                    href.match(/homeq\\.se\\/\\d{5,}/)
                ) {
                    const clean = href.split('?')[0].split('#')[0];
                    if (!seen.has(clean)) {
                        seen.add(clean);
                        results.push(clean);
                    }
                }
            }
            return results;
        }
        """
    )

    if not urls:
        # Try broader search — any homeq.se link that looks like a detail page
        urls = await page.evaluate(
            """
            () => {
                const seen = new Set();
                const results = [];
                const links = Array.from(document.querySelectorAll('a[href]'));
                for (const a of links) {
                    const href = a.href || '';
                    if (!href.includes('homeq.se')) continue;
                    // Skip known navigation pages
                    const skip = ['/p/', '/search', '/sok', '/landlord',
                                  '/login', '/register', '/om-oss', '/kontakt'];
                    if (skip.some(s => href.includes(s))) continue;
                    // Must have a path segment that looks like an ID or slug
                    const path = new URL(href).pathname;
                    const segments = path.split('/').filter(Boolean);
                    if (segments.length >= 2) {
                        const clean = href.split('?')[0].split('#')[0];
                        if (!seen.has(clean)) {
                            seen.add(clean);
                            results.push(clean);
                        }
                    }
                }
                return results;
            }
            """
        )
        if urls:
            print(f"  (Broader search found {len(urls)} candidate URLs)")

    return urls


async def _scrape_apartment(page, url: str) -> dict | None:
    """Visit an apartment detail page and extract Uthyrningsdetaljer."""
    await page.goto(url, wait_until="networkidle", timeout=60000)
    await asyncio.sleep(1.5)

    apt_title = (await page.title()).strip()

    # Try __NEXT_DATA__ first — most reliable on Next.js apps
    next_data = await _try_next_data(page)

    uthyrning = {}
    if next_data:
        uthyrning = _extract_from_next_data(next_data)

    # DOM fallback
    if not uthyrning:
        uthyrning = await _extract_from_dom(page)

    return {
        "url": url,
        "title": apt_title,
        "scraped_at": datetime.now(timezone.utc).isoformat(),
        "uthyrningsdetaljer": uthyrning,
    }


async def _try_next_data(page) -> dict | None:
    el = await page.query_selector("#__NEXT_DATA__")
    if not el:
        return None
    try:
        return json.loads(await el.inner_text())
    except Exception:
        return None


def _extract_from_next_data(data: dict) -> dict:
    """Walk Next.js page props to collect rental detail fields."""
    result = {}

    # Common HomeQ key paths under pageProps
    def search(obj, depth=0):
        if depth > 12 or not isinstance(obj, (dict, list)):
            return
        if isinstance(obj, list):
            for item in obj:
                search(item, depth + 1)
            return
        rental_keys = {
            "rent", "hyra", "monthlyRent", "monthlyCost",
            "area", "yta", "livingArea",
            "rooms", "rum", "numberOfRooms",
            "floor", "våning",
            "moveInDate", "tillträde", "availableFrom",
            "type", "objectType", "housingType",
            "address", "street", "city", "postalCode",
            "deposit", "depositMonths",
            "landlordName", "landlord",
            "size", "squareMeters",
            "heating", "electricity",
        }
        for k, v in obj.items():
            k_lower = k.lower()
            if any(rk in k_lower for rk in rental_keys):
                if isinstance(v, (str, int, float, bool)):
                    result[k] = str(v)
            search(v, depth + 1)

    search(data)
    return result


async def _extract_from_dom(page) -> dict:
    """Extract Uthyrningsdetaljer from the rendered HTML DOM."""
    return await page.evaluate(
        """
        () => {
            const result = {};
            const norm = s => (s || '').replace(/\\s+/g, ' ').trim();

            // ── Strategy 1: Find "Uthyrningsdetaljer" heading ────────────────
            const allEls = Array.from(document.querySelectorAll('*'));
            for (const el of allEls) {
                const text = el.childNodes.length === 1
                    ? norm(el.textContent)
                    : '';
                if (!text.toLowerCase().includes('uthyrningsdetaljer')) continue;
                if (text.length > 40) continue; // Not a heading if too long

                // Walk upward to find a section container, then look inside it
                let section = el.parentElement;
                for (let i = 0; i < 4 && section; i++) {
                    // dl pattern
                    const dts = section.querySelectorAll('dt');
                    const dds = section.querySelectorAll('dd');
                    if (dts.length > 0 && dts.length === dds.length) {
                        dts.forEach((dt, i) => {
                            const k = norm(dt.textContent);
                            const v = norm(dds[i].textContent);
                            if (k) result[k] = v;
                        });
                        if (Object.keys(result).length > 0) return result;
                    }

                    // Grid / pair pattern
                    const items = section.querySelectorAll(
                        '[class*="row"], [class*="item"], [class*="field"], li'
                    );
                    for (const item of items) {
                        const ch = Array.from(item.children);
                        if (ch.length >= 2) {
                            const k = norm(ch[0].textContent);
                            const v = norm(ch[1].textContent);
                            if (k && k !== v) result[k] = v;
                        }
                    }
                    if (Object.keys(result).length > 0) return result;

                    section = section.parentElement;
                }
                break;
            }

            // ── Strategy 2: Any <dl> with rental-looking terms ────────────────
            const rentalTerms = ['hyra', 'yta', 'rum', 'våning', 'tillträde',
                                 'inflyttning', 'storlek', 'typ'];
            for (const dl of document.querySelectorAll('dl')) {
                const dts = dl.querySelectorAll('dt');
                const dds = dl.querySelectorAll('dd');
                if (!dts.length) continue;
                const firstLabel = norm(dts[0].textContent).toLowerCase();
                if (!rentalTerms.some(t => firstLabel.includes(t))) continue;
                dts.forEach((dt, i) => {
                    const k = norm(dt.textContent);
                    const v = norm(dds[i]?.textContent);
                    if (k) result[k] = v || '';
                });
                if (Object.keys(result).length > 0) return result;
            }

            // ── Strategy 3: Scan for key-value grids in "details" sections ───
            const detailSections = document.querySelectorAll(
                '[class*="detail"], [class*="info-box"], [class*="spec"], [class*="facts"]'
            );
            for (const sec of detailSections) {
                const children = Array.from(sec.children);
                if (children.length < 4) continue;
                // Try even/odd pairing
                for (let i = 0; i + 1 < children.length; i += 2) {
                    const k = norm(children[i].textContent);
                    const v = norm(children[i + 1].textContent);
                    if (k && v && k !== v && k.length < 50) result[k] = v;
                }
                if (Object.keys(result).length > 2) return result;
            }

            return result;
        }
        """
    )


def _dump_debug(html: str, url: str):
    """Write page HTML to a temp file for debugging."""
    debug_path = Path("data") / "homeq_debug.html"
    debug_path.parent.mkdir(exist_ok=True)
    debug_path.write_text(html)
    print(f"  Page HTML saved to {debug_path} (URL was: {url})")
    print("  All <a> hrefs:")
    import re
    hrefs = re.findall(r'href="([^"]+)"', html)
    for href in hrefs[:40]:
        print(f"    {href}")


if __name__ == "__main__":
    asyncio.run(main())
