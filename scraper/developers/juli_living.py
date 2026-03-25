"""Scraper for Juli Living — rental apartments listed on HomeQ.

Source URL: https://www.homeq.se/p/nrep

Strategy:
  1. Navigate to the NREP landlord profile on HomeQ (React/Next.js SPA).
  2. Wait for listing cards to render, then collect all apartment detail URLs.
  3. Handle pagination via the "next page" button or URL query params.
  4. For each apartment detail page, extract every field listed under the
     "Uthyrningsdetaljer" heading as a raw key→value dict.
  5. Return a single Project ("Juli Living") whose apartments list contains
     one dict per rental unit.

Environment variable PAGE_LIMIT (int, default 0 = all pages) can be used to
cap how many pages are fetched (useful for testing: PAGE_LIMIT=1).
"""
import asyncio
import json
import os
import re
from datetime import datetime, timezone
from playwright.async_api import Browser, Page

from ..base import BaseScraper
from ..models import Project

BASE_URL = "https://www.homeq.se/p/nrep"
PAGE_LIMIT = int(os.environ.get("PAGE_LIMIT", "0"))  # 0 = no limit


class JuliLivingScraper(BaseScraper):
    name = "Juli Living"
    url = BASE_URL

    async def scrape(self, browser: Browser) -> list:
        ctx = await self._new_context(browser)
        page = await ctx.new_page()
        apartments = []

        try:
            listing_urls = await _collect_listing_urls(page, page_limit=PAGE_LIMIT)
            print(f"[JuliLiving] Found {len(listing_urls)} listings")

            for url in listing_urls:
                try:
                    apt = await _scrape_apartment(page, url)
                    if apt:
                        apartments.append(apt)
                        hyra = apt.get("uthyrningsdetaljer", {}).get("Hyra", "?")
                        print(f"[JuliLiving] {apt.get('title', url)} | {hyra}")
                except Exception as exc:
                    print(f"[JuliLiving] Error scraping {url}: {exc}")

        finally:
            await ctx.close()

        print(f"[JuliLiving] Done — {len(apartments)} apartments")
        return [
            Project(
                developer="Juli Living",
                id="juli-living-homeq",
                name="Juli Living",
                url=BASE_URL,
                location="Sweden",
                status="selling",
                apartments=apartments,
                available_units=len(apartments),
            )
        ]


# ── Listing URL collection ─────────────────────────────────────────────────


async def _collect_listing_urls(page: Page, page_limit: int = 0) -> list[str]:
    """
    Navigate the NREP landlord profile, collecting all apartment detail URLs.
    Handles pagination by following "next page" links / buttons.
    """
    collected: set[str] = set()
    page_num = 1

    current_url = BASE_URL
    while True:
        print(f"[JuliLiving] Fetching page {page_num}: {current_url}")
        await page.goto(current_url, wait_until="networkidle", timeout=90000)
        await asyncio.sleep(2)

        urls = await _extract_listing_urls_from_page(page)
        new = [u for u in urls if u not in collected]
        collected.update(new)
        print(f"[JuliLiving]   → {len(new)} new listings (total: {len(collected)})")

        if page_limit and page_num >= page_limit:
            break

        next_url = await _get_next_page_url(page, page_num)
        if not next_url:
            break
        current_url = next_url
        page_num += 1

    return sorted(collected)


async def _extract_listing_urls_from_page(page: Page) -> list[str]:
    """Extract all apartment detail page URLs from the current listing page."""
    return await page.evaluate(
        """
        () => {
            const seen = new Set();
            const results = [];
            const links = Array.from(document.querySelectorAll('a[href]'));
            for (const a of links) {
                const href = a.href || '';
                // HomeQ detail pages match /listing/{id} or /object/{id}
                // or sometimes are numeric like /12345
                if (
                    href.includes('homeq.se') &&
                    (
                        href.match(/\\/listing\\/\\d+/) ||
                        href.match(/\\/object\\/\\d+/) ||
                        href.match(/\\/bostad\\/\\d+/) ||
                        href.match(/\\/lagenhet\\/\\d+/) ||
                        href.match(/homeq\\.se\\/\\d{4,}/)
                    )
                ) {
                    const clean = href.split('?')[0];
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


async def _get_next_page_url(page: Page, current_page: int) -> str | None:
    """
    Detect if there is a next page and return its URL.
    HomeQ uses either:
      (a) a "next" button/link with rel="next" or aria-label containing "nästa"
      (b) URL query parameter ?page=N
    """
    next_url: str | None = await page.evaluate(
        """
        () => {
            // rel="next" link in <head>
            const rel = document.querySelector('link[rel="next"]');
            if (rel) return rel.href;

            // <a> with text/aria matching "nästa" / "next" / ">"
            const anchors = Array.from(document.querySelectorAll('a'));
            for (const a of anchors) {
                const text = (a.textContent || '').trim().toLowerCase();
                const aria = (a.getAttribute('aria-label') || '').toLowerCase();
                if (
                    text === 'nästa' || text === 'next' || text === '›' || text === '»' ||
                    aria.includes('nästa') || aria.includes('next page') ||
                    (a.getAttribute('rel') || '').includes('next')
                ) {
                    return a.href || null;
                }
            }

            // Button with next-page intent (not a link, look for disabled state)
            const buttons = Array.from(document.querySelectorAll('button'));
            for (const btn of buttons) {
                const text = (btn.textContent || '').trim().toLowerCase();
                const aria = (btn.getAttribute('aria-label') || '').toLowerCase();
                if (
                    (text.includes('nästa') || aria.includes('nästa') || aria.includes('next')) &&
                    !btn.disabled
                ) {
                    // Can't get href from button, signal via sentinel
                    return '__BUTTON_NEXT__';
                }
            }

            return null;
        }
        """
    )

    if not next_url:
        return None

    if next_url == "__BUTTON_NEXT__":
        # Build next page URL from current URL pattern
        current = page.url
        if "page=" in current:
            return re.sub(r"page=\d+", f"page={current_page + 1}", current)
        sep = "&" if "?" in current else "?"
        return f"{current}{sep}page={current_page + 1}"

    # Validate it's still on homeq.se
    if "homeq.se" not in next_url:
        return None
    return next_url


# ── Apartment detail scraping ──────────────────────────────────────────────


async def _scrape_apartment(page: Page, url: str) -> dict | None:
    """Navigate to an apartment detail page and extract all available data."""
    await page.goto(url, wait_until="networkidle", timeout=60000)
    await asyncio.sleep(1.5)

    title = (await page.title()).strip()

    # Try __NEXT_DATA__ first (most reliable on Next.js sites)
    next_data = await _extract_next_data(page)
    uthyrning = _parse_uthyrning_from_next_data(next_data) if next_data else {}

    # Fall back to DOM extraction if next_data didn't yield results
    if not uthyrning:
        uthyrning = await _extract_uthyrning_from_dom(page)

    if not uthyrning:
        return None

    return {
        "url": url,
        "title": title,
        "scraped_at": datetime.now(timezone.utc).isoformat(),
        "uthyrningsdetaljer": uthyrning,
    }


async def _extract_next_data(page: Page) -> dict | None:
    """Extract embedded Next.js __NEXT_DATA__ JSON."""
    el = await page.query_selector("#__NEXT_DATA__")
    if not el:
        return None
    try:
        text = await el.inner_text()
        return json.loads(text)
    except Exception:
        return None


def _parse_uthyrning_from_next_data(data: dict) -> dict:
    """
    Walk the Next.js page props to find rental detail fields.
    HomeQ typically embeds listing data under pageProps.listing or similar.
    """
    result = {}

    def walk(obj, depth=0):
        if depth > 10 or not isinstance(obj, (dict, list)):
            return
        if isinstance(obj, list):
            for item in obj:
                walk(item, depth + 1)
            return
        # Look for keys that suggest rental details
        rental_keys = {
            "rent", "hyra", "monthlyRent", "area", "yta", "rooms", "rum",
            "floor", "våning", "moveIn", "tillträde", "type", "typ",
            "address", "adress", "size", "storlek",
        }
        for k, v in obj.items():
            k_lower = k.lower()
            if any(rk in k_lower for rk in rental_keys) and isinstance(v, (str, int, float)):
                result[k] = str(v)
            else:
                walk(v, depth + 1)

    walk(data)
    return result


async def _extract_uthyrning_from_dom(page: Page) -> dict:
    """
    Parse the "Uthyrningsdetaljer" section from the rendered DOM.
    Tries multiple structural patterns used on HomeQ.
    """
    return await page.evaluate(
        """
        () => {
            const result = {};

            // Helper: normalize a label string
            const norm = s => (s || '').replace(/\\s+/g, ' ').trim();

            // Strategy 1: find the heading, then parse its container
            const headings = Array.from(document.querySelectorAll(
                'h1, h2, h3, h4, h5, h6, [class*="heading"], [class*="title"]'
            ));
            for (const h of headings) {
                if (!h.textContent.toLowerCase().includes('uthyrningsdetaljer')) continue;

                // Try parent's next sibling, then direct next sibling
                const containers = [
                    h.nextElementSibling,
                    h.parentElement?.nextElementSibling,
                    h.closest('section, div[class*="section"], div[class*="card"]'),
                ].filter(Boolean);

                for (const container of containers) {
                    // dl/dt/dd
                    const dts = container.querySelectorAll('dt');
                    const dds = container.querySelectorAll('dd');
                    if (dts.length > 0) {
                        dts.forEach((dt, i) => {
                            const key = norm(dt.textContent);
                            const val = norm(dds[i]?.textContent);
                            if (key) result[key] = val;
                        });
                        if (Object.keys(result).length > 0) return result;
                    }

                    // div/span pairs (label + value siblings)
                    const items = container.querySelectorAll(
                        '[class*="row"], [class*="item"], [class*="detail"], [class*="field"], li'
                    );
                    for (const item of items) {
                        const children = Array.from(item.children);
                        if (children.length >= 2) {
                            const key = norm(children[0].textContent);
                            const val = norm(children[1].textContent);
                            if (key) result[key] = val;
                        }
                    }
                    if (Object.keys(result).length > 0) return result;
                }
                break;
            }

            // Strategy 2: any dl element with rental-looking dt labels
            const rentalLabels = ['hyra', 'yta', 'rum', 'våning', 'tillträde',
                                  'inflyttning', 'typ', 'storlek', 'adress'];
            const dls = Array.from(document.querySelectorAll('dl'));
            for (const dl of dls) {
                const dts = dl.querySelectorAll('dt');
                const dds = dl.querySelectorAll('dd');
                if (dts.length === 0) continue;
                const firstLabel = (dts[0]?.textContent || '').toLowerCase();
                if (!rentalLabels.some(l => firstLabel.includes(l))) continue;
                dts.forEach((dt, i) => {
                    const key = norm(dt.textContent);
                    const val = norm(dds[i]?.textContent);
                    if (key) result[key] = val;
                });
                if (Object.keys(result).length > 0) return result;
            }

            // Strategy 3: look for div-based key-value grids in the page body
            // Often HomeQ uses a grid where odd children are labels, even are values
            const grids = Array.from(document.querySelectorAll(
                '[class*="detail"], [class*="info"], [class*="spec"], [class*="facts"]'
            ));
            for (const grid of grids) {
                const children = Array.from(grid.children);
                if (children.length < 2) continue;
                // Pair-wise: label, value, label, value...
                for (let i = 0; i < children.length - 1; i += 2) {
                    const key = norm(children[i].textContent);
                    const val = norm(children[i + 1].textContent);
                    if (key && val) result[key] = val;
                }
                if (Object.keys(result).length > 2) return result;
            }

            return result;
        }
        """
    )
