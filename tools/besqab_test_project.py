"""Test scrape of a single Besqab project page.

Prints every apartment row found in any table/list on the page,
along with a dump of all text visible on the page for debugging.
"""
import asyncio
from playwright.async_api import async_playwright

URL = "https://www.besqab.se/stockholm/bro-malarstad/slottsparken/"


async def main():
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        ctx = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            locale="sv-SE",
            timezone_id="Europe/Stockholm",
            extra_http_headers={"Accept-Language": "sv-SE,sv;q=0.9"},
        )
        await ctx.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
        """)
        page = await ctx.new_page()

        print(f"Navigating to: {URL}")
        resp = await page.goto(URL, wait_until="networkidle", timeout=60000)
        print(f"HTTP status: {resp.status}")
        await asyncio.sleep(2)

        title = await page.title()
        print(f"Page title: {title}")

        h1 = await page.query_selector("h1")
        if h1:
            print(f"H1: {await h1.inner_text()}")

        # Dump all <table> elements
        tables = await page.evaluate("""
            () => {
                const out = [];
                document.querySelectorAll('table').forEach((tbl, ti) => {
                    const headerEls = tbl.querySelectorAll('thead th, thead td');
                    const firstRow = tbl.querySelector('tr');
                    const headers = headerEls.length
                        ? Array.from(headerEls).map(el => el.innerText.trim())
                        : firstRow ? Array.from(firstRow.querySelectorAll('th,td')).map(el => el.innerText.trim()) : [];
                    const rows = [];
                    tbl.querySelectorAll('tbody tr').forEach(tr => {
                        const cells = Array.from(tr.querySelectorAll('td,th')).map(el => el.innerText.trim());
                        if (cells.some(c => c)) rows.push(cells);
                    });
                    out.push({ table_index: ti, headers, rows });
                });
                return out;
            }
        """)

        print(f"\n=== TABLES FOUND: {len(tables)} ===")
        for t in tables:
            print(f"\n-- Table {t['table_index']} --")
            print(f"   Headers: {t['headers']}")
            print(f"   Rows ({len(t['rows'])}):")
            for row in t['rows']:
                print(f"     {row}")

        # Dump elements with apartment-related class names
        apt_els = await page.evaluate("""
            () => {
                const keywords = ['apartment','bostad','unit','listing','lagenh','object','home','hem','residence'];
                const found = [];
                document.querySelectorAll('*').forEach(el => {
                    const cls = (el.className || '').toLowerCase();
                    if (keywords.some(k => cls.includes(k))) {
                        const text = el.innerText ? el.innerText.trim() : '';
                        if (text) found.push({ tag: el.tagName, cls: el.className, text: text.slice(0, 300) });
                    }
                });
                const seen = new Set();
                return found.filter(f => {
                    if (seen.has(f.text)) return false;
                    seen.add(f.text);
                    return true;
                }).slice(0, 30);
            }
        """)

        print(f"\n=== APARTMENT-RELATED ELEMENTS ({len(apt_els)}) ===")
        for el in apt_els:
            print(f"  <{el['tag']} class=\"{el['cls']}\">")
            print(f"    {repr(el['text'][:200])}")

        # Full visible page text
        body_text = await page.evaluate("() => document.body.innerText")
        print(f"\n=== PAGE TEXT (first 4000 chars) ===")
        print(body_text[:4000])

        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
