"""Standalone script to discover all project URLs on besqab.se.

Run with:  python tools/besqab_discover.py
Outputs a list of discovered project URLs and the link structure found
on each crawled page, so we can understand the site layout.
"""
import asyncio
from urllib.parse import urlparse
from playwright.async_api import async_playwright

BASE_URL = "https://www.besqab.se"

NAV_SLUGS = {
    "kontakt", "om-oss", "om-besqab", "hallbarhet", "hållbarhet",
    "investerare", "press", "karriar", "karriär", "nyheter",
    "integritetspolicy", "cookies", "sitemap", "search", "sök", "404",
    "gdpr", "tillganglighetsredogorelse",
}

SEED_PATHS = [
    "/",
    "/stockholm/",
    "/uppsala/",
    "/vastmanland/",
    "/vara-projekt/",
    "/projekt/",
    "/bostader/",
    "/hitta-bostad/",
    "/nya-bostader/",
]


def normalize(url: str) -> str | None:
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
    if any(s in NAV_SLUGS for s in segments):
        return None
    import re
    if re.search(r"\.[a-z]{2,4}$", segments[-1]):
        return None
    return f"https://www.besqab.se{path}"


def depth(url: str) -> int:
    return len([s for s in urlparse(url).path.strip("/").split("/") if s])


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

        visited = set()
        depth1_urls = set()
        depth2_urls = set()
        project_urls = set()   # depth 3
        to_visit = [BASE_URL + p for p in SEED_PATHS]

        while to_visit:
            url = to_visit.pop(0)
            if url in visited:
                continue
            visited.add(url)

            print(f"\n>>> Visiting ({depth(url)}-deep): {url}")
            try:
                resp = await page.goto(url, wait_until="domcontentloaded", timeout=30000)
                print(f"    Status: {resp.status}")
                await asyncio.sleep(1)
            except Exception as e:
                print(f"    ERROR: {e}")
                continue

            links = await page.eval_on_selector_all("a[href]", "els => els.map(e => e.href)")
            new_at_this_level = []

            for link in links:
                norm = normalize(link)
                if not norm or norm in visited:
                    continue
                d = depth(norm)
                if d == 1:
                    depth1_urls.add(norm)
                    if norm not in to_visit:
                        to_visit.append(norm)
                elif d == 2:
                    depth2_urls.add(norm)
                    if norm not in to_visit:
                        to_visit.append(norm)
                elif d == 3:
                    project_urls.add(norm)
                new_at_this_level.append((d, norm))

            for d, u in sorted(set(new_at_this_level)):
                print(f"    [{d}] {u}")

        await browser.close()

    print("\n" + "=" * 60)
    print(f"DEPTH-1 pages ({len(depth1_urls)}):")
    for u in sorted(depth1_urls):
        print(f"  {u}")

    print(f"\nDEPTH-2 pages ({len(depth2_urls)}):")
    for u in sorted(depth2_urls):
        print(f"  {u}")

    print(f"\nPROJECT pages / depth-3 ({len(project_urls)}):")
    for u in sorted(project_urls):
        print(f"  {u}")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
