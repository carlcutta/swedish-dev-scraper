"""Scraper for Peab Bostad - peab.se
Strategy:
  1. XHR interception on /bostad/ listing
  2. DOM fallback
"""
import re
from playwright.async_api import Browser
from ..base import BaseScraper
from ..models import Project


class PeabScraper(BaseScraper):
    name = "Peab"
    url = "https://www.peab.se"

    async def scrape(self, browser: Browser) -> list:
        ctx = await self._new_context(browser)
        page = await ctx.new_page()
        projects = []

        try:
            data = await self._intercept_json(
                page,
                f"{self.url}/bostad/",
                r"(api|search|projekt|bostad)",
            )
            if data:
                items = _dig_list(data)
                projects = [p for p in (_parse(i, self.name, self.url) for i in items) if p]

            if not projects:
                nd = await self._next_data(page, f"{self.url}/bostad/")
                if nd:
                    from .jm import _dig_list as jm_dig
                    items = jm_dig(nd, ["props", "pageProps", "projects"])
                    projects = [p for p in (_parse(i, self.name, self.url) for i in items) if p]

            if not projects:
                soup = await self._rendered_soup(page, f"{self.url}/bostad/")
                for card in soup.select(".project-card, .bostad-projekt, article[data-id], [class*='projekt']"):
                    p = _parse_dom(card, self.name, self.url)
                    if p:
                        projects.append(p)

        finally:
            await ctx.close()

        print(f"[Peab] {len(projects)} projects")
        return projects


def _dig_list(data) -> list:
    if isinstance(data, list): return data
    if isinstance(data, dict):
        for k in ["projects", "items", "result", "data", "bostader"]:
            if k in data:
                v = data[k]
                if isinstance(v, list): return v
    return []


def _parse(item: dict, dev: str, base_url: str) -> Project | None:
    if not isinstance(item, dict): return None
    name = item.get("name") or item.get("title") or item.get("projektNamn") or ""
    if not name: return None
    pid = str(item.get("id") or item.get("projectId") or item.get("projektId") or "")
    location = item.get("city") or item.get("ort") or item.get("municipality") or ""
    municipality = item.get("municipality") or item.get("kommun") or location
    county = item.get("county") or item.get("lan") or ""
    raw_url = item.get("url") or item.get("href") or item.get("slug") or ""
    url = raw_url if str(raw_url).startswith("http") else f"{base_url}{raw_url}"
    if not url: url = f"{base_url}/bostad/{pid}"
    total = _int(item.get("totalUnits") or item.get("antalBostader") or item.get("numberOfUnits"))
    available = _int(item.get("availableUnits") or item.get("ledigaBostader") or item.get("tillSalu"))
    sold = _int(item.get("soldUnits") or item.get("saldaBostader"))
    if total and available is not None and sold is None: sold = total - available
    status = _status(item.get("status") or item.get("projektStatus") or "")
    price_from = _price(item.get("priceFrom") or item.get("prisFrom") or item.get("startpris"))
    price_to = _price(item.get("priceTo") or item.get("prisTill"))
    monthly_from = _price(item.get("monthlyFeeFrom") or item.get("avgiftFrom"))
    monthly_to = _price(item.get("monthlyFeeTo") or item.get("avgiftTill"))
    move_in = str(item.get("moveInDate") or item.get("inflyttning") or item.get("beraknadInflyttning") or "")
    housing = _housing(item.get("housingType") or item.get("bostadsTyp") or "")
    return Project(
        developer=dev,
        id=f"peab-{pid}" if pid else f"peab-{name.lower().replace(' ', '-')}",
        name=name, url=url, location=location, municipality=municipality, county=county,
        status=status, housing_types=housing,
        total_units=total, available_units=available, sold_units=sold,
        price_from=price_from, price_to=price_to,
        monthly_fee_from=monthly_from, monthly_fee_to=monthly_to,
        move_in_date=move_in[:10] if move_in else None,
    )


def _parse_dom(card, dev: str, base_url: str) -> Project | None:
    name_el = card.select_one("h2, h3, .project-name, [class*='title']")
    name = name_el.get_text(strip=True) if name_el else ""
    if not name: return None
    link = card.select_one("a[href]")
    url = link["href"] if link else ""
    if url and not url.startswith("http"): url = base_url + url
    return Project(developer=dev, id=f"peab-{name.lower().replace(' ', '-')}",
                   name=name, url=url or base_url, location="", municipality="", county="", status="selling")


def _int(v) -> int | None:
    if v is None: return None
    try: return int(str(v).replace(" ", "").replace("\xa0", ""))
    except: return None

def _price(v) -> int | None:
    if v is None: return None
    s = re.sub(r"[^\d.]", "", str(v))
    try: return int(float(s))
    except: return None

def _status(raw: str) -> str:
    r = raw.lower()
    if any(k in r for k in ["plan", "kommande", "coming"]): return "planning"
    if any(k in r for k in ["sold", "slutsåld", "såld"]): return "sold_out"
    if any(k in r for k in ["klar", "completed", "inflyttad", "färdig"]): return "completed"
    return "selling"

def _housing(raw) -> list:
    if not raw: return []
    if isinstance(raw, list): return [str(h).lower() for h in raw]
    s = str(raw).lower()
    out = []
    if any(k in s for k in ["lägenhet", "apartment", "bostadsrätt"]): out.append("apartment")
    if any(k in s for k in ["radhus", "townhouse"]): out.append("townhouse")
    if any(k in s for k in ["villa", "kedjehus"]): out.append("villa")
    return out or [s]
