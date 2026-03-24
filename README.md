# Swedish Developer Scraper

Daily scraping of Swedish residential developer sales statistics, published as a static website via GitHub Pages.

## Developers tracked

| Developer | Website |
|-----------|---------|
| JM AB | jm.se |
| Riksbyggen | riksbyggen.se |
| HSB | hsb.se |
| Peab Bostad | peab.se |
| Skanska Nya Hem | skanska.se |
| Bonava | bonava.se |

## Architecture

```
.github/workflows/scrape.yml   → Daily GitHub Actions job (06:00 UTC)
scraper/                       → Python scrapers (Playwright + BeautifulSoup)
data/
  latest/                      → Latest snapshot per developer + combined all.json
  snapshots/YYYY-MM-DD/        → Daily archive
  index.json                   → Snapshot index for website history charts
docs/                          → Static website (GitHub Pages)
runner.py                      → Entry point
```

**Scraping strategy per site (three-tier fallback):**
1. XHR/fetch JSON interception — capture the API call the page makes internally
2. `__NEXT_DATA__` / `__NUXT_DATA__` — parse embedded JSON from Next.js/Nuxt pages
3. Rendered DOM — parse fully-rendered HTML with BeautifulSoup

## Local setup

```bash
pip install -r requirements.txt
playwright install chromium --with-deps

# Run all scrapers
python runner.py

# Run a single developer
python runner.py JM
python runner.py Riksbyggen HSB
```

## GitHub Pages setup

1. Go to **Settings → Pages**
2. Source: **Deploy from branch**
3. Branch: `main` / Folder: `/docs`

The website reads data from `../data/` (same repo, same origin).

## GitHub Actions secrets (optional)

| Secret | Purpose |
|--------|---------|
| `PROXY_URL` | Residential proxy URL if GitHub Actions IPs get blocked |

## Data schema

Each developer's snapshot (`data/latest/{developer}.json`):

```json
{
  "developer": "JM",
  "scraped_at": "2026-03-24T06:12:34",
  "project_count": 42,
  "error": null,
  "projects": [
    {
      "developer": "JM",
      "id": "jm-12345",
      "name": "Brf Rosendal",
      "url": "https://www.jm.se/...",
      "location": "Uppsala",
      "municipality": "Uppsala",
      "county": "Uppsala län",
      "status": "selling",
      "housing_types": ["apartment"],
      "total_units": 80,
      "available_units": 12,
      "sold_units": 68,
      "price_from": 2950000,
      "price_to": 5800000,
      "monthly_fee_from": 3200,
      "monthly_fee_to": 5100,
      "move_in_date": "2026-Q4",
      "scraped_at": "2026-03-24T06:12:34"
    }
  ]
}
```
