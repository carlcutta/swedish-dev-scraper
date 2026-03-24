"""Scraper for Besqab - besqab.se
Strategy:
  1. XHR interception on /bostader/
  2. __NEXT_DATA__ / __NUXT_DATA__ fallback
  3. DOM fallback
"""
import re
from playwright.async_api import Browser
from ..base import BaseScraper
from ..models import Project


LISTING_PATHS = ["/bostader/", "/projekt/", "/lediga-bostader/"]


class BesqabScraper(BaseScraper):
    name = "Besqab"
    url = "https://www.besqab.se"

    async def scrape(self, browser: Browser) -> list:
        ctx = await self._new_context(browser)
        page = await ctx.new_page()
        projects = []

        try:
            for path in LISTING_PATHS:
                listing_url = f"{self.url}{path}"

                # Strategy 1: intercept XHR JSON
                data = await self._intercept_json(
                    page,
                    listing_url,
                    r"(api|project|bostad|hem|homes|listings)",
                )
                if data:
                    items = _dig_list(data)
                    projects = [p for p in (_parse(i, self.name, self.url) for i in items) if p]
                    if projects:
                        break

                # Strategy 2: __NEXT_DATA__ / __NUXT_DATA__
                if not projects:
                    nd = await self._next_data(page, listing_url)
                    if nd:
                        items = (
                            _dig_list(nd.get("props", {}).get("pageProps", {}).get("projects"))
                            or _dig_list(nd.get("props", {}).get("pageProps", {}).get("homes"))
                            or _dig_list(nd.get("props", {}).get("pageProps", {}).get("items"))
                            or _dig_list(nd)
                        )
                        projects = [p for p in (_parse(i, self.name, self.url) for i in items) if p]
                        if projects:
                            break

                # Strategy 3: DOM fallback
                if not projects:
                    soup = await self._rendered_soup(page, listing_url)
                    cards = (
                        soup.select("[class*='project-card']")
                        or soup.select("[class*='ProjectCard']")
                        or soup.select("[class*='listing-item']")
                        or soup.select("article[class*='project']")
                        or soup.select("article[class*='bostad']")
                        or soup.select(".card")
                    )
                    for card in cards:
                        p = _parse_dom(card, self.name, self.url)
                        if p:
                            projects.append(p)
                    if projects:
                        break

        finally:
            await ctx.close()

        print(f"[Besqab] {len(projects)} projects")
        return projects


def _dig_list(data) -> list:
    if data is None:
        return []
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for k in ["projects", "items", "data", "homes", "results", "listings", "bostader"]:
            if k in data:
                v = data[k]
                if isinstance(v, list):
                    return v
                if isinstance(v, dict):
                    inner = _dig_list(v)
                    if inner:
                        return inner
    return []


def _parse(item: dict, dev: str, base_url: str) -> Project | None:
    if not isinstance(item, dict):
        return None
    name = (
        item.get("name") or item.get("title") or item.get("projectName")
        or item.get("heading") or item.get("projectTitle") or ""
    )
    if not name:
        return None
    pid = str(
        item.get("id") or item.get("projectId") or item.get("externalId")
        or item.get("slug") or ""
    )
    location = item.get("city") or item.get("location") or item.get("municipality") or item.get("area") or ""
    municipality = item.get("municipality") or item.get("kommun") or location
    county = item.get("county") or item.get("region") or item.get("lan") or ""
    raw_url = item.get("url") or item.get("href") or item.get("link") or item.get("slug") or ""
    if str(raw_url).startswith("http"):
        url = raw_url
    elif raw_url:
        url = base_url + ("/" if not str(raw_url).startswith("/") else "") + raw_url
    else:
        url = f"{base_url}/bostader/{pid}" if pid else base_url
    total = _int(item.get("totalUnits") or item.get("numberOfUnits") or item.get("totalHomes") or item.get("antal"))
    available = _int(
        item.get("availableUnits") or item.get("availableHomes")
        or item.get("forSale") or item.get("ledigaBostader")
    )
    sold = _int(item.get("soldUnits") or item.get("soldHomes") or item.get("sold"))
    if total and available is not None and sold is None:
        sold = total - available
    status = _status(item.get("status") or item.get("saleStatus") or item.get("phase") or item.get("stage") or "")
    if available == 0 and total:
        status = "sold_out"
    price_from = _price(item.get("priceFrom") or item.get("startPrice") or item.get("minPrice") or item.get("prisFrom"))
    price_to = _price(item.get("priceTo") or item.get("maxPrice") or item.get("prisTill"))
    monthly_from = _price(item.get("monthlyFeeFrom") or item.get("avgiftFrom") or item.get("fee"))
    monthly_to = _price(item.get("monthlyFeeTo") or item.get("avgiftTo"))
    move_in = str(
        item.get("moveInDate") or item.get("completionDate") or item.get("readyDate")
        or item.get("inflyttning") or item.get("inflyttningsDatum") or ""
    )
    housing = _housing(item.get("housingType") or item.get("homeType") or item.get("bostadstyp") or "")
    return Project(
        developer=dev,
        id=f"besqab-{pid}" if pid else f"besqab-{name.lower().replace(' ', '-')}",
        name=name, url=url, location=location, municipality=municipality, county=county,
        status=status, housing_types=housing,
        total_units=total, available_units=available, sold_units=sold,
        price_from=price_from, price_to=price_to,
        monthly_fee_from=monthly_from, monthly_fee_to=monthly_to,
        move_in_date=move_in[:10] if move_in else None,
    )


def _parse_dom(card, dev: str, base_url: str) -> Project | None:
    name_el = card.select_one("h2, h3, h4, [class*='title'], [class*='name'], [class*='heading']")
    name = name_el.get_text(strip=True) if name_el else ""
    if not name:
        return None
    link = card.select_one("a[href]")
    url = link["href"] if link else ""
    if url and not url.startswith("http"):
        url = base_url + url
    pid = name.lower().replace(" ", "-")
    return Project(
        developer=dev,
        id=f"besqab-{pid}",
        name=name, url=url or base_url,
        location="", municipality="", county="", status="selling",
    )


def _int(v) -> int | None:
    if v is None:
        return None
    try:
        return int(str(v).replace(" ", "").replace("\xa0", ""))
    except Exception:
        return None


def _price(v) -> int | None:
    if v is None:
        return None
    s = re.sub(r"[^\d.]", "", str(v))
    try:
        return int(float(s))
    except Exception:
        return None


def _status(raw: str) -> str:
    r = raw.lower()
    if any(k in r for k in ["plan", "kommande", "coming", "upcoming", "future"]):
        return "planning"
    if any(k in r for k in ["sold", "slutsåld", "såld", "sold out"]):
        return "sold_out"
    if any(k in r for k in ["klar", "completed", "inflyttad", "ready", "färdig"]):
        return "completed"
    return "selling"


def _housing(raw) -> list:
    if not raw:
        return []
    if isinstance(raw, list):
        return [str(h).lower() for h in raw]
    s = str(raw).lower()
    out = []
    if any(k in s for k in ["lägenhet", "apartment", "bostadsrätt", "br"]):
        out.append("apartment")
    if any(k in s for k in ["radhus", "townhouse", "parhus"]):
        out.append("townhouse")
    if any(k in s for k in ["villa", "kedjehus"]):
        out.append("villa")
    return out or [s]
