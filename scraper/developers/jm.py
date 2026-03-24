"""Scraper for JM AB - jm.se
Strategy:
  1. Intercept XHR JSON from /hitta-bostad/ listing
  2. Try __NEXT_DATA__ embedded JSON
  3. Parse rendered DOM
"""
import re
from playwright.async_api import Browser
from ..base import BaseScraper
from ..models import Project


class JMScraper(BaseScraper):
    name = "JM"
    url = "https://www.jm.se"

    async def scrape(self, browser: Browser) -> list:
        ctx = await self._new_context(browser)
        page = await ctx.new_page()
        projects = []

        try:
            # Strategy 1: intercept XHR JSON
            data = await self._intercept_json(
                page,
                f"{self.url}/hitta-bostad/",
                r"(api|search|project|bostad)",
            )
            if data:
                items = _dig_list(data, ["projects", "items", "result", "hits", "data"])
                projects = [p for p in (_parse(i, self.name, self.url) for i in items) if p]

            # Strategy 2: __NEXT_DATA__
            if not projects:
                nd = await self._next_data(page, f"{self.url}/hitta-bostad/")
                if nd:
                    items = _dig_list(nd, ["props", "pageProps", "projects"]) or \
                            _dig_list(nd, ["props", "pageProps", "initialData", "projects"])
                    projects = [p for p in (_parse(i, self.name, self.url) for i in items) if p]

            # Strategy 3: DOM fallback
            if not projects:
                soup = await self._rendered_soup(page, f"{self.url}/hitta-bostad/")
                for card in soup.select("[data-project-id], .project-card, article.project"):
                    p = _parse_dom(card, self.name, self.url)
                    if p:
                        projects.append(p)

        finally:
            await ctx.close()

        print(f"[JM] {len(projects)} projects")
        return projects


def _dig_list(data, keys: list) -> list:
    """Walk a nested dict trying each key in sequence."""
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for k in keys:
            if k in data:
                v = data[k]
                if isinstance(v, list):
                    return v
                if isinstance(v, dict):
                    return _dig_list(v, keys)
    return []


def _parse(item: dict, dev: str, base_url: str) -> Project | None:
    if not isinstance(item, dict):
        return None
    name = item.get("name") or item.get("projectName") or item.get("title") or ""
    if not name:
        return None
    pid = str(item.get("id") or item.get("projectId") or item.get("projectNumber") or "")
    location = item.get("city") or item.get("municipality") or item.get("location") or ""
    municipality = item.get("municipality") or item.get("municipalityName") or location
    county = item.get("county") or item.get("region") or ""
    slug = item.get("slug") or item.get("url") or pid
    url = slug if str(slug).startswith("http") else f"{base_url}/hitta-bostad/{slug}"
    total = _int(item.get("totalUnits") or item.get("numberOfUnits"))
    available = _int(item.get("availableUnits") or item.get("numberOfAvailableUnits") or item.get("unitsForSale"))
    sold = _int(item.get("soldUnits") or item.get("numberOfSoldUnits"))
    if total and available is not None and sold is None:
        sold = total - available
    status = _status(item.get("status") or item.get("projectStatus") or "")
    if available == 0 and total:
        status = "sold_out"
    price_from = _price(item.get("priceFrom") or item.get("minPrice"))
    price_to   = _price(item.get("priceTo")   or item.get("maxPrice"))
    move_in = str(item.get("moveInDate") or item.get("occupancyDate") or item.get("completionDate") or "")
    housing = _housing(item.get("housingType") or item.get("dwellingType") or "")
    return Project(
        developer=dev,
        id=f"jm-{pid}" if pid else f"jm-{name.lower().replace(' ', '-')}",
        name=name, url=url, location=location, municipality=municipality, county=county,
        status=status, housing_types=housing,
        total_units=total, available_units=available, sold_units=sold,
        price_from=price_from, price_to=price_to,
        move_in_date=move_in[:10] if move_in else None,
    )


def _parse_dom(card, dev: str, base_url: str) -> Project | None:
    name_el = card.select_one("h2, h3, .project-name, [class*='title']")
    name = name_el.get_text(strip=True) if name_el else ""
    if not name:
        return None
    pid = card.get("data-project-id") or card.get("data-id") or ""
    link = card.select_one("a[href]")
    url = link["href"] if link else f"{base_url}/hitta-bostad/{pid}"
    if url and not url.startswith("http"):
        url = base_url + url
    return Project(developer=dev, id=f"jm-{pid or name.lower().replace(' ', '-')}",
                   name=name, url=url, location="", municipality="", county="", status="selling")


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
    if any(k in r for k in ["plan", "coming", "kommande", "upcoming"]): return "planning"
    if any(k in r for k in ["sold", "såld", "slutsåld"]): return "sold_out"
    if any(k in r for k in ["complete", "färdig", "inflyttad", "klar"]): return "completed"
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
