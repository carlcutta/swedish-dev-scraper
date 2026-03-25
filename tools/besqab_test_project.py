"""Test scrape of a single Besqab project page.

Targets the apartment table with headers:
  Nummer, Vaning, Antal rum, Storlek, Pris, Avgift, Status
"""
import asyncio
from playwright.async_api import async_playwright

URL = "https://www.besqab.se/stockholm/danderyd/hertha/"

EXPECTED_HEADERS = {"nummer", "våning", "antal rum", "storlek", "pris", "avgift", "status"}


async def main():
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

        print(f"Navigating to: {URL}")
        resp = await page.goto(URL, wait_until="networkidle", timeout=60000)
        print(f"HTTP status: {resp.status}")
        await asyncio.sleep(2)

        print(f"Page title: {await page.title()}")
        h1 = await page.query_selector("h1")
        if h1:
            print(f"H1: {await h1.inner_text()}")

        # Extract every <table> and check which one has our headers
        tables = await page.evaluate("""
            () => {
                return Array.from(document.querySelectorAll('table')).map((tbl, ti) => {
                    const headerEls = tbl.querySelectorAll('thead th, thead td');
                    const firstRow = tbl.querySelector('tr');
                    const headers = headerEls.length
                        ? Array.from(headerEls).map(el => el.innerText.trim())
                        : firstRow
                            ? Array.from(firstRow.querySelectorAll('th,td')).map(el => el.innerText.trim())
                            : [];
                    const rows = Array.from(tbl.querySelectorAll('tbody tr')).map(tr =>
                        Array.from(tr.querySelectorAll('td,th')).map(el => el.innerText.trim())
                    ).filter(cells => cells.some(c => c));
                    return { table_index: ti, headers, rows };
                });
            }
        """)

        print(f"\n=== {len(tables)} TABLE(S) FOUND ===")
        for t in tables:
            headers_lower = {h.lower() for h in t['headers']}
            match = EXPECTED_HEADERS & headers_lower
            print(f"\n-- Table {t['table_index']} (headers match: {sorted(match)}) --")
            print(f"   Headers : {t['headers']}")
            print(f"   Row count: {len(t['rows'])}")
            for row in t['rows']:
                print(f"   {row}")

        # Also try scanning for div/list-based tables with those header texts
        print("\n=== SCANNING FOR DIV-BASED TABLE ===")
        div_data = await page.evaluate("""
            () => {
                // Find any element whose direct text contains our header words
                const targets = ['Nummer','Vaning','Antal rum','Storlek','Pris','Avgift','Status',
                                 'V\u00e5ning','antal','pris','avgift','status','storlek'];
                const found = [];
                document.querySelectorAll('*').forEach(el => {
                    if (el.children.length < 2) return;
                    const text = el.innerText || '';
                    const hits = targets.filter(t => text.toLowerCase().includes(t.toLowerCase()));
                    if (hits.length >= 3) {
                        found.push({
                            tag: el.tagName,
                            cls: el.className,
                            hits,
                            text: text.trim().slice(0, 600)
                        });
                    }
                });
                // Return smallest matching containers (most specific)
                found.sort((a, b) => a.text.length - b.text.length);
                const seen = new Set();
                return found.filter(f => {
                    if (seen.has(f.text)) return false;
                    seen.add(f.text);
                    return true;
                }).slice(0, 10);
            }
        """)

        for el in div_data:
            print(f"\n  <{el['tag']} class=\"{el['cls']}\"> hits={el['hits']}")
            print(f"  {repr(el['text'])}")

        # Full page text so we can see what's actually there
        body = await page.evaluate("() => document.body.innerText")
        print("\n=== FULL PAGE TEXT (first 5000 chars) ===")
        print(body[:5000])

        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
